# dpulse.py
# DPULSE main entrypoint (CLI). Added guarded rich import and headless API function.

import sys
import os
from colorama import Fore, Style, Back
import traceback
from pathlib import Path
import threading
from time import sleep, time

# keep your existing sys.path additions (so internal modules import as before)
sys.path.append('datagather_modules')
sys.path.append('service')
sys.path.append('reporting_modules')
sys.path.append('dorking')
sys.path.append('apis')
sys.path.append('snapshotting')

# Guarded import for `rich` so importing dpulse does not fail when `rich` isn't installed
try:
    from rich.progress import Progress, SpinnerColumn, TextColumn  # type: ignore
    RICH_AVAILABLE = True
except Exception:
    RICH_AVAILABLE = False

# Other imports that your code expects (leave as-is)
try:
    import socket
    import re
    import webbrowser
    import sqlite3
    import itertools
    from colorama import Fore, Style, Back  # already imported above, but harmless
except ImportError as e:
    print(Fore.RED + f"Import error appeared. Reason: {e}" + Style.RESET_ALL)
    # Do not exit on import here — let callers decide. But for safety in CLI, we will still exit.
    # sys.exit()

# Now import project modules (these use the sys.path additions above)
from config_processing import create_config, check_cfg_presence, read_config, print_and_return_config

# existing config/checks
cfg_presence = check_cfg_presence()
if cfg_presence:
    print(Fore.GREEN + "Global config file presence: OK" + Style.RESET_ALL)
else:
    print(Fore.RED + "Global config file presence: NOT OK")
    create_config()
    print(Fore.GREEN + "Successfully generated global config file")

import db_processing as db
import cli_init
from dorking_handler import dorks_files_check
from data_assembler import DataProcessing
from logs_processing import logging
from db_creator import get_columns_amount

rsdb_presence = db.check_rsdb_presence('report_storage.db')
if rsdb_presence:
    print(Fore.GREEN + "Report storage database presence: OK" + Style.RESET_ALL)
else:
    db.db_creation('report_storage.db')
    print(Fore.GREEN + "Successfully created report storage database" + Style.RESET_ALL)

dorks_files_check()

try:
    data_processing = DataProcessing()
    config_values = read_config()
except Exception:
    # keep going; for headless usage, some components can be missing/initialized lazily
    data_processing = None
    config_values = None

cli = cli_init.Menu()
cli.welcome_menu()

# ---------------------------------------------------------------------------
# process_report (your original function, replicated with small layout changes)
# ---------------------------------------------------------------------------
def process_report(report_filetype, short_domain, url, case_comment, keywords_list, keywords_flag,
                   dorking_flag, used_api_flag, pagesearch_flag, pagesearch_ui_mark, spinner_thread,
                   snapshotting_flag, snapshotting_ui_mark, username, from_date, end_date):
    import xlsx_report_creation as xlsx_rc
    import html_report_creation as html_rc
    from misc import time_processing

    try:
        start = time()
        # `data_processing` is the same instance created above
        if pagesearch_flag in ['y', 'si']:
            data_array, report_info_array = data_processing.data_gathering(
                short_domain, url, report_filetype.lower(), pagesearch_flag.lower(), keywords_list,
                keywords_flag, dorking_flag.lower(), used_api_flag, snapshotting_flag, username, from_date, end_date
            )
        else:
            data_array, report_info_array = data_processing.data_gathering(
                short_domain, url, report_filetype.lower(), pagesearch_flag.lower(), '',
                keywords_flag, dorking_flag.lower(), used_api_flag, snapshotting_flag, username, from_date, end_date
            )
        end = time() - start
        endtime_string = time_processing(end)

        if report_filetype == 'xlsx':
            xlsx_rc.create_report(short_domain, url, case_comment, data_array, report_info_array, pagesearch_ui_mark, endtime_string, snapshotting_ui_mark)
        elif report_filetype == 'html':
            html_rc.report_assembling(short_domain, url, case_comment, data_array, report_info_array, pagesearch_ui_mark, endtime_string, snapshotting_ui_mark)
    finally:
        # ensure spinner thread stops if provided
        try:
            spinner_thread.do_run = False
            spinner_thread.join()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Rich spinner thread (kept the same)
# ---------------------------------------------------------------------------
class RichProgressBar(threading.Thread):
    def __init__(self):
        super(RichProgressBar, self).__init__()
        self.do_run = True

    def run(self):
        # if `rich` isn't available, bail early (spinner won't run)
        if not RICH_AVAILABLE:
            while self.do_run:
                sleep(0.25)
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[magenta]Processing scan...[/magenta]"),
            transient=True,
        ) as progress:
            task = progress.add_task("", total=None)
            while self.do_run:
                progress.update(task)
                sleep(0.1)

# ---------------------------------------------------------------------------
# New: headless API function streamlit can call
# ---------------------------------------------------------------------------
def run_headless_scan(
    short_domain: str,
    report_filetype: str = "html",
    pagesearch_flag: str = "n",
    keywords_list: list | None = None,
    dorking_flag: str = "n",
    used_api_flag: list | None = None,
    snapshotting_flag: str = "n",
    username: str | None = None,
    from_date: str | None = None,
    end_date: str | None = None,
    log_callback=None,
):
    """
    Run DPULSE in headless mode (callable from Streamlit).
    Returns dict { success: bool, message: str, report_files: [paths...], trace?: str }
    """
    def _log(msg: str):
        try:
            if log_callback:
                log_callback(str(msg))
            else:
                # fallback to printing when no callback provided
                print(str(msg))
        except Exception:
            # swallow logging errors
            pass

    try:
        _log(f"Starting headless scan for: {short_domain}")
        if not short_domain or "." not in short_domain:
            return {"success": False, "message": "Invalid domain provided", "report_files": []}

        # Attempt to import the domain precheck helper if available
        try:
            from misc import domain_precheck
        except Exception:
            domain_precheck = None

        # Optionally perform domain precheck
        if domain_precheck:
            _log("Performing domain precheck...")
            try:
                ok = domain_precheck(short_domain)
                if not ok:
                    return {"success": False, "message": "Domain precheck failed (not reachable)", "report_files": []}
                _log("Domain precheck passed.")
            except Exception as e:
                _log(f"Domain precheck threw: {e} — continuing anyway")

        # Normalize flags
        keywords_flag = 1 if keywords_list else 0
        if not used_api_flag:
            used_api_flag = ["Empty"]
        if from_date is None:
            from_date = "N"
        if end_date is None:
            end_date = "N"

        # Start spinner if rich is available
        spinner_thread = None
        if RICH_AVAILABLE:
            spinner_thread = RichProgressBar()
            spinner_thread.start()
        else:
            _log("RICH not available -> no fancy spinner. Running scan in headless mode.")

        try:
            # call the same helper you use for CLI
            process_report(
                report_filetype,
                short_domain,
                f"http://{short_domain}/",
                "",                      # case_comment - none in headless mode
                keywords_list,
                keywords_flag,
                dorking_flag,
                used_api_flag,
                pagesearch_flag,
                "Yes" if pagesearch_flag.lower() == "y" else "No",
                spinner_thread,
                snapshotting_flag,
                "Yes" if snapshotting_flag.lower() != "n" else "No",
                username,
                from_date,
                end_date,
            )
        finally:
            # ensure spinner stops
            if spinner_thread:
                spinner_thread.do_run = False
                spinner_thread.join()

        # collect generated reports for this domain in the reports directory
        report_dir = Path("reports")
        created = []
        if report_dir.exists():
            for p in report_dir.glob(f"{short_domain}*"):
                created.append(str(p.resolve()))

        _log("Headless scan finished.")
        return {"success": True, "message": "Scan finished", "report_files": created}
    except Exception as e:
        return {"success": False, "message": str(e), "report_files": [], "trace": traceback.format_exc()}

# ---------------------------------------------------------------------------
# CLI run() — keep your original interactive menu intact below
# ---------------------------------------------------------------------------
def run():
    while True:
        try:
            cli.print_main_menu()
            domain_patter = r'^(?!\-)(?:[a-zA-Z0-9\-]{1,63}\.)+[a-zA-Z]{2,}$'
            choice = input(Fore.YELLOW + "\nEnter your choice >> ")
            if choice == "1":
                from misc import domain_precheck
                print(Fore.GREEN + "\nImported and activated reporting modules" + Style.RESET_ALL)
                while True:
                    short_domain = input(Fore.YELLOW + "\nEnter target's domain name (or 'back' to return to the menu) >> ")
                    if short_domain.lower() == "back":
                        print(Fore.RED + "\nReturned to main menu")
                        break
                    else:
                        if not short_domain:
                            print(Fore.RED + "\nEmpty domain names are not supported")
                        elif re.match(domain_patter, short_domain) is None:
                            print(Fore.RED + '\nYour string does not match domain pattern')
                        else:
                            url = "http://" + short_domain + "/"
                            print(Fore.GREEN + 'Pinging domain...' + Style.RESET_ALL, end = ' ')
                            if domain_precheck(short_domain):
                                print(Fore.GREEN + 'Entered domain is accessible. Continuation' + Style.RESET_ALL)
                            else:
                                print(Fore.RED + "Entered domain is not accessible. Scan is impossible" + Style.RESET_ALL)
                                break
                            case_comment = input(Fore.YELLOW + "Enter case comment >> ")
                            report_filetype = input(Fore.YELLOW + "Enter report file extension [HTML/XLSX] >> ")
                            if not report_filetype:
                                print(Fore.RED + "\nReport filetype cannot be empty")
                            if report_filetype.lower() not in ['html', 'xlsx']:
                                print(Fore.RED + '\nTemporarily you have to choose only HTML report file type')
                            else:
                                pagesearch_flag = input(Fore.YELLOW + "Would you like to use PageSearch function? [Y/N (for No)] >> ")
                                if pagesearch_flag.lower() == 'y':
                                    keywords_input = input(Fore.YELLOW + "Enter keywords (separate by comma) to search in files during PageSearch process (or write N if you don't need it) >> ")
                                    if keywords_input.lower() != "n":
                                        if len(keywords_input.lower()) > 0:
                                            keywords_list = [keyword.strip() for keyword in keywords_input.split(',')]
                                            keywords_flag = 1
                                        else:
                                            print(Fore.RED + "\nThis field must contain at least one keyword")
                                            break
                                    elif keywords_input.lower() == "n":
                                        keywords_list = None
                                        keywords_flag = 0
                                elif pagesearch_flag.lower() == 'n':
                                    keywords_list = None
                                    keywords_flag = 0
                                if report_filetype.lower() == 'html' or report_filetype.lower() == 'xlsx':
                                    dorking_flag = input(Fore.YELLOW + "Select Dorking mode [Basic/IoT/Files/Admins/Web/Custom/N (for None)] >> ")
                                    api_flag = input(Fore.YELLOW + "Would you like to use 3rd party API in scan? [Y/N (for No)] >> ")
                                    if api_flag.lower() == 'y':
                                        print(Fore.GREEN + "\nSupported APIs and your keys:\n")
                                        db.select_api_keys('printing')
                                        print(Fore.GREEN + "Pay attention that APIs with red-colored API Key field are unable to use!\n")
                                        to_use_api_flag = input(Fore.YELLOW + "Select APIs IDs you want to use in scan (separated by comma) >> ")
                                        used_api_flag = [item.strip() for item in to_use_api_flag.split(',')]
                                        if '3' in used_api_flag:
                                            username = input(Fore.YELLOW + "If you know some username from this domain, please enter it here (or N if not) >> ")
                                        else:
                                            username = None
                                        if db.check_api_keys(used_api_flag):
                                            print(Fore.GREEN + 'Found API key. Continuation')
                                        else:
                                            print(Fore.RED + "\nAPI key was not found. Check if you've entered valid API key in API Keys DB")
                                            break
                                        used_api_ui = f'Yes, using APIs with following IDs: {", ".join(used_api_flag)}'
                                    elif api_flag.lower() == 'n':
                                        used_api_ui = 'No'
                                        used_api_flag = ['Empty']
                                        username = None
                                        pass
                                    else:
                                        print(Fore.RED + "\nInvalid API usage mode" + Style.RESET_ALL)
                                        break
                                    snapshotting_flag = input(Fore.YELLOW + "Select Snapshotting mode [S(creenshot)/P(age Copy)/W(ayback Machine)/N (for None)] >> ")
                                    if pagesearch_flag.lower() == 'y' or pagesearch_flag.lower() == 'n':
                                        if pagesearch_flag.lower() == "n":
                                            pagesearch_ui_mark = 'No'
                                        elif pagesearch_flag.lower() == 'y' and keywords_flag == 1:
                                            pagesearch_ui_mark = f'Yes, with {keywords_list} keywords search'
                                        else:
                                            pagesearch_ui_mark = 'Yes, without keywords search'
                                        if dorking_flag.lower() not in ['basic', 'iot', 'n', 'admins', 'files', 'web', 'custom']:
                                            print(Fore.RED + "\nInvalid Dorking mode. Please select mode among Basic/IoT/Files/Web/Admins/Custom or N")
                                            break
                                        else:
                                            dorking_ui_mark = 'No'
                                            if dorking_flag.lower() in ('basic', 'iot', 'files', 'admins', 'web'):
                                                db_name = {
                                                    'basic': 'basic_dorking.db',
                                                    'iot': 'iot_dorking.db',
                                                    'files': 'files_dorking.db',
                                                    'admins': 'adminpanels_dorking.db',
                                                    'web': 'webstructure_dorking.db'}[dorking_flag.lower()]
                                                row_count = get_columns_amount(f'dorking//{db_name}', f'{dorking_flag.lower()}_dorks')
                                                dorking_ui_mark = f'Yes, {dorking_flag.lower().replace("_", " ")} dorking ({row_count} dorks)'
                                            elif dorking_flag.lower() == 'custom':
                                                custom_db_name = str(input(Fore.YELLOW + "Enter your custom Dorking DB name (without any file extensions) >> "))
                                                row_count = get_columns_amount(f'dorking//{custom_db_name}.db', 'dorks')
                                                dorking_ui_mark = f'Yes, Custom table dorking ({row_count} dorks)'
                                                dorking_flag = str(dorking_flag.lower() + f"+{custom_db_name}.db")
                                        if snapshotting_flag.lower() not in ['s', 'p', 'w', 'n']:
                                            print(Fore.RED + "\nInvalid Snapshotting mode. Please select mode among S/P/W or N")
                                            break
                                        else:
                                            snapshotting_ui_mark = 'No'
                                            from_date = end_date = 'N'
                                            if snapshotting_flag.lower() == 's':
                                                from_date = end_date = 'N'
                                                snapshotting_ui_mark = "Yes, domain's main page snapshotting as a screenshot"
                                            elif snapshotting_flag.lower() == 'p':
                                                from_date = end_date = 'N'
                                                snapshotting_ui_mark = "Yes, domain's main page snapshotting as a .HTML file"
                                            elif snapshotting_flag.lower() == 'w': 
                                                from_date = str(input('Enter start date (YYYYMMDD format): '))
                                                end_date = str(input('Enter end date (YYYYMMDD format): '))
                                                snapshotting_ui_mark = "Yes, domain's main page snapshotting using Wayback Machine"
                                        cli_init.print_prescan_summary(short_domain, report_filetype.upper(), pagesearch_ui_mark, dorking_ui_mark, used_api_ui, case_comment, snapshotting_ui_mark)
                                        #print(Fore.LIGHTMAGENTA_EX + "[BASIC SCAN START]\n" + Style.RESET_ALL)
                                        spinner_thread = RichProgressBar()
                                        spinner_thread.start()
                                        if report_filetype.lower() in ['html', 'xlsx']:
                                            process_report(report_filetype, short_domain, url, case_comment,
                                                           keywords_list, keywords_flag, dorking_flag, used_api_flag,
                                                           pagesearch_flag, pagesearch_ui_mark, spinner_thread, snapshotting_flag, snapshotting_ui_mark, username, from_date, end_date)
                                    else:
                                        print(Fore.RED + "\nUnsupported PageSearch mode. Please choose between Y or N")

            elif choice == "2":
                import configparser
                cli.print_settings_menu()
                choice_settings = input(Fore.YELLOW + "\nEnter your choice >> ")
                if choice_settings == '1':
                    print_and_return_config()
                elif choice_settings == '2':
                    config = print_and_return_config()
                    section = input(Fore.YELLOW + "\nEnter the section you want to update >> ")
                    if not config.has_section(section.upper()):
                        print(Fore.RED + "\nSection you've entered does not exist in config file. Please verify that section name is correct")
                        pass
                    else:
                        option = input(Fore.YELLOW + "Enter the option you want to update >> ")
                        if not config.has_option(section.upper(), option):
                            print(Fore.RED + "\nOption you've entered does not exist in config file. Please verify that option name is correct")
                            pass
                        else:
                            value = input(Fore.YELLOW + "Enter the new value >> ")
                            config.set(section.upper(), option, value)
                            with open('service//config.ini', 'w') as configfile:
                                config.write(configfile)
                            print(Fore.GREEN + "\nConfiguration updated successfully" + Style.RESET_ALL)
                elif choice_settings == '3':
                    with open('journal.log', 'w'):
                        print(Fore.GREEN + "Journal file was successfully cleared" + Style.RESET_ALL)
                        pass
                elif choice_settings == '4':
                    continue
            elif choice == '3':
                cli.dorking_db_manager()
                choice_dorking = input(Fore.YELLOW + "\nEnter your choice >> ")
                if choice_dorking == '1':
                    from db_creator import manage_dorks
                    cli_init.print_api_db_msg()
                    ddb_name = input(Fore.YELLOW + "Enter a name for your custom Dorking DB (without any extensions) >> ")
                    manage_dorks(ddb_name)
                elif choice_dorking == '2':
                    continue
            elif choice == "6":
                webbrowser.open('https://dpulse.readthedocs.io/en/latest/')

            elif choice == '5':
                cli.api_manager()
                choice_api = input(Fore.YELLOW + "\nEnter your choice >> ")
                if choice_api == '1':
                    print(Fore.GREEN + "\nSupported APIs and your keys:\n")
                    cursor, conn = db.select_api_keys('updating')
                    api_id_to_update = input(Fore.YELLOW + "Enter API's ID to update its key >> ")
                    new_api_key = input(Fore.YELLOW + "Enter new API key >> ")

                    try:
                        cursor.execute("""
                            UPDATE api_keys 
                            SET api_key = ? 
                            WHERE id = ?
                        """, (new_api_key, api_id_to_update))

                        conn.commit()
                        conn.close()
                        print(Fore.GREEN + "\nSuccessfully added new API key" + Style.RESET_ALL)
                    except Exception as e:
                        print(Fore.RED + "Something went wrong when adding new API key. See journal for details" + Style.RESET_ALL)
                        logging.error(f'API KEY ADDING: ERROR. REASON: {e}')

                elif choice_api == '2':
                    import shutil
                    try:
                        os.remove('apis//api_keys.db')
                        print(Fore.GREEN + "Deleted old API Keys DB")
                    except FileNotFoundError:
                        print(Fore.RED + "API Keys DB was not found")
                    try:
                        shutil.copyfile('apis//api_keys_reference.db', 'apis//api_keys.db')
                        print(Fore.GREEN + "Successfully restored reference API Keys DB")
                    except FileNotFoundError:
                        print(Fore.RED + "Reference API Keys DB was not found")
                else:
                    continue

            elif choice == "4":
                cli.print_db_menu()
                rsdb_presence = db.check_rsdb_presence('report_storage.db')
                if rsdb_presence:
                    print(Fore.GREEN + "\nReport storage database presence: OK\n" + Style.RESET_ALL)
                else:
                    db.db_creation('report_storage.db')
                    print(Fore.GREEN + "Successfully created report storage database" + Style.RESET_ALL)
                choice_db = input(Fore.YELLOW + "Enter your choice >> ")
                if choice_db == "1":
                    cursor, sqlite_connection, data_presence_flag = db.db_select()
                elif choice_db == "2":
                    cursor, sqlite_connection, data_presence_flag = db.db_select()
                    if data_presence_flag:
                        id_to_extract = int(input(Fore.YELLOW + "\nEnter report ID you want to extract >> "))
                        extracted_folder_name = f'report_recreated_ID#{id_to_extract}'
                        try:
                            os.makedirs(extracted_folder_name)
                            db.db_report_recreate(extracted_folder_name, id_to_extract)
                        except FileExistsError:
                            print(Fore.RED + "Report with the same recreated folder already exists. Please check its content or delete it and try again" + Style.RESET_ALL)
                        except Exception as e:
                            print(Fore.RED + "Error appeared when trying to recreate report from DB. See journal for details" + Style.RESET_ALL)
                    else:
                        pass
                elif choice_db == "3":
                    print(Fore.GREEN + "\nDatabase connection is successfully closed")
                    continue
            elif choice == "7":
                print(Fore.RED + "Exiting the program." + Style.RESET_ALL)
                break
            else:
                print(Fore.RED + "\nInvalid menu item. Please select between existing menu items")
        except KeyboardInterrupt:
            print(Fore.RED + "\nDPULSE process was ended using keyboard" + Style.RESET_ALL)
            sys.exit()

if __name__ == "__main__":
    run()
