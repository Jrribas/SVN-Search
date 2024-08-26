import os
import sys
import signal
import sqlite3
import traceback

from time import sleep
from typing import List

from subprocess import Popen, PIPE
from natsort import os_sorted
from PySide6.QtWidgets import QPushButton, QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox
from PySide6.QtCore import QThread, Signal, Slot, QObject


class CustomException(Exception):
    """Custom exception class"""
    pass


class WorkerScrapeRepo(QObject):
    """
    Worker which will run in another thread to avoid GUI blocking.
    Scrapes the svn repository and populates the database.
    """
    # Defining all class function. Instance variables are defined in the __init__ function.
    finished = Signal()
    error_during_task = Signal(tuple)
    user_interrupted = Signal()
    add_item_list = Signal(str)
    broadcast_pid = Signal(int)
    broadcast_thread_status = Signal(bool)

    def __init__(self, db_path: str, url: str, rev: str, root_folder: str, max_tries: int, max_level: int):
        """
        :param db_path: database filepath
        :param url: full folder path (url) in the svn repo to scrape
        :param rev: revision to be used
        :param root_folder: root folder for SVN repository ex: "repo" in https://djsfkdjfn.com/repo/
        """
        super().__init__()
        self.db_path = db_path
        self.url = url
        self.rev = rev
        self.root_folder = root_folder
        self.max_tries = max_tries
        self.max_level = max_level

    @Slot()
    def work(self):
        """
        Work\\Run function where the main function (generate_database) is called and checks are defined
        (finished with errors or successfully).
        """
        try:
            self.broadcast_thread_status.emit(True)
            self.generate_database()
        except:
            # traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.error_during_task.emit((exctype, value, traceback.format_exc()))
        else:
            if self.thread().isInterruptionRequested():
                self.user_interrupted.emit()
            else:
                self.finished.emit()
        finally:
            self.broadcast_thread_status.emit(False)

    def generate_database(self):
        """
        Creates the database file, scrapes the svn repo provided and populates the database.

        Example database:
        +------------------+----------+--------+--------+
        | id (primary key) | parentid | isfile | value  |
        +==================+==========+========+========+
        |         1        |    -1    |    0   |  repo  |
        |         2        |     1    |    1   | ola.py |
        +------------------+----------+--------+--------+
        """
        server_url = self.url[:self.url.find(self.root_folder)]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stack = [(self.url, 0)]

        id_mapping = {}
        first = True
        while stack and not self.thread().isInterruptionRequested():
            url, level = stack.pop()
            self.add_item_list.emit(url)

            if level < self.max_level:
                output = self.svn_list(url, recursive=False, first=first)
            else:
                output = self.svn_list(url, recursive=True, first=first)

            if first:
                first = False

            if not output:
                continue

            if level < self.max_level:
                for path in output[::-1]:
                    if path[-1] == "/":
                        stack.append((server_url + path, level + 1))

            id_mapping = self.populate_db(output, id_mapping, cursor)
            conn.commit()

        conn.commit()
        conn.close()
        del cursor, conn

    def svn_list(self, url: str, recursive: bool, first: bool) -> List[str]:
        """
        Runs a non-recursive or recursive svn list command with the provided url and revision.
        If an error occurs when running the command svn list then the script will try again in 5 min. This will repeat
        if this parameter is not 0. Errors currently checked: E175002, E730065, E170013, E731001, E175012, E120108,
        E200009, svn help list (complete failure when running command)

        :param url: url to use svn list
        :param recursive: if the command will only output first children or all items inside the folder
        :param first: If it is the first connection, and it fails then it should throw a different error
        :return: A list with all lines of the output ordered by folders and then files. Both individually ordered by
                 os_sorted.
        """
        if recursive:
            cmd = ["svn", "ls", "-R", url + "@" + self.rev]
        else:
            cmd = ["svn", "ls", url + "@" + self.rev]

        # Run the svn list command.
        process = Popen(cmd, stdout=PIPE, stderr=PIPE)

        # Get the PID
        pid = process.pid
        self.broadcast_pid.emit(pid)

        output, errors = process.communicate()

        tries_count = 0
        err_mssg = str(errors)
        if err_mssg:
            print(err_mssg)
        # E160006: Invalid revision
        # E200009: Could not list all targets because some targets don't exist
        # E170000: Illegal repository url
        # E170013: Unable to connect to repository url.
        # E731001: Host is unknown.
        # E175002: Connection failure
        # E730065: Host unreachable.
        # E175012: Connection timed out
        # E120108: The server unexpectedly closed the connection

        if "E160006" in err_mssg:
            print(err_mssg)
            raise CustomException("This revision is not valid: %s" % self.rev)
        elif "E200009" in err_mssg:
            print(err_mssg)
            raise CustomException("Couldn't find this folder: %s" % url)
        elif "E170000" in err_mssg:
            print(err_mssg)
            raise CustomException("The url is not correct or repository is incorrectly configured: %s" % url)
        elif "E731001" in err_mssg and "E170013" in err_mssg and first:
            print(err_mssg)
            raise CustomException("Check the url and the internet connection adn try again. \n %s" % url)

        while ("E175002" in err_mssg or "E730065" in err_mssg or "E170013" in err_mssg or "E175012" in err_mssg
               or "E120108" in err_mssg or "E731001" in err_mssg):
            if tries_count == self.max_tries:
                raise CustomException("Error: Couldn't connect to svn server even after %s tries." % self.max_tries)
            tries_count += 1
            print("Entered loop")
            self.add_item_list.emit("Encountered connection problems. Trying again in 2min.")
            sleep(5)

            # Run the svn list command
            process = Popen(cmd, stdout=PIPE, stderr=PIPE)

            # Get the PID
            pid = process.pid
            self.broadcast_pid.emit(pid)

            output, errors = process.communicate()

        if not self.thread().isInterruptionRequested():
            output = self.fix_output(url, output)

        return output

    def fix_output(self, url: str, output: bytes) -> list[str]:
        """
        This function does two things to fix the output of svn list:

        1. Adds the parents folders to all lines of the output
        2. Orders the output by folders and then files with both individually ordered using os_sorted

        :param url: url used in the svn list command
        :param output: svn list output
        :return: A list with all lines of the output ordered by folders and then files. Both individually ordered by
                 os_sorted
        """
        if not output:
            return []

        server_url = url[:url.find(self.root_folder)]
        prefix = url.replace(server_url, "")

        # Separate files from folders and order them individually.
        files = []
        folders = []
        output = str(output.decode("latin1"))[:-2]
        output = output.split("\r\n")
        if not isinstance(output, list):
            output = [output]
        for path in output:
            if path[-1] == "/":
                folders.append(path)
            else:
                files.append(path)

        # and them together with first folders and then files.
        files = os_sorted(files)
        folders = os_sorted(folders)

        updated_output = []
        for path in folders + files:
            updated_output.append(prefix + path)

        return updated_output

    @staticmethod
    def populate_db(output: list, id_mapping: dict, cursor: sqlite3.Cursor) -> dict:
        """
        Populates the database file created with data from the svn list commands. Updates the id_mapping to continue
        correctly the id_mapping for next set of data.

        :param output: Fixed output from svn list command
        :param id_mapping: Dictionary where all the information we are inserting in the database is also present.
                           Good for debugging.
        :param cursor: Cursor of the database created. Used to insert rows.
        :return: id mapping updated with new set of data and ready for next set.
        """
        # If this is the first time we are populating id_mapping then define current_id as 1. If not get the latest id
        # used and increment.
        if id_mapping:
            current_id = id_mapping[list(id_mapping.keys())[-1]][0] + 1
        else:
            current_id = 1

        # Cycle through all paths\lines in the output
        for path in output:
            # If it is a folder then define isfile a 0 and remove the empty item it is created by the final "/"
            if path[-1] == "/":
                path_parts = path.split('/')[:-1]
                isfile = 0
            else:
                path_parts = path.split('/')
                isfile = 1

            parent_path = ''
            parent_id = -1

            # Cycle through all parts of the path to check if they were already created and created them if necessary
            for part in path_parts:
                current_path = parent_path + part
                # If current paths is not yet created populate id_mapping and the database
                if current_path not in id_mapping:
                    id_mapping[current_path] = [current_id, parent_id, isfile]
                    cursor.execute('''INSERT INTO repository (id, parentid, isfile, value) 
                                      VALUES (?, ?, ?, ?)''', (current_id, parent_id, isfile, part))
                    current_id += 1
                parent_id = id_mapping[current_path][0]
                parent_path += part + '/'

        return id_mapping


class SVNScrapper(QDialog):
    def __init__(self, parent, repo=None):
        super().__init__(parent)
        self.setWindowTitle("SVN Scrapper")
        self.resize(400, 100)

        if not repo:
            self.repo = self.parent().repo
        else:
            self.repo = repo

        self.pid = None
        self.finished_okay = None
        self.finished_on_error = None
        self.finished_by_user = None
        self.thread_running = None

        layout = QVBoxLayout()
        self.label = QLabel("The scrapper is working in the background. For very large repositories "
                            "(5 million folders/files) it could take as long as 3 days.")
        layout.addWidget(self.label)

        self.list = QListWidget()
        layout.addWidget(self.list)

        self.button = QPushButton("Cancel")
        self.button.pressed.connect(self.cancel_button_verification)
        layout.addWidget(self.button)

        self.setLayout(layout)

        self.thread = QThread()
        self.thread.setObjectName("scrape_svn_repo")

        self.worker = WorkerScrapeRepo(self.repo.db_path, self.repo.url, self.repo.rev, self.repo.root_folder,
                                       self.repo.max_tries, self.repo.max_level)

        self.worker.add_item_list.connect(self.update_list)
        self.worker.broadcast_pid.connect(self.save_process_id)
        self.worker.finished.connect(self.stop_on_task_finished)
        self.worker.error_during_task.connect(self.stop_on_error)
        self.worker.user_interrupted.connect(self.stop_on_user_interruption)
        self.worker.broadcast_thread_status.connect(self.update_thread_status)

        self.thread.started.connect(self.worker.work)
        self.worker.moveToThread(self.thread)
        self.thread.start()

    def update_thread_status(self, thread_status):
        self.thread_running = thread_status

    @Slot(str)
    def update_list(self, item_text: str):
        """Add new item to the List widget"""
        item = QListWidgetItem(item_text)
        self.list.addItem(item)
        self.list.scrollToItem(item)

    @Slot(int)
    def save_process_id(self, pid):
        """Save latest pid so it can be terminate if user decides"""
        self.pid = pid

    def closeEvent(self, event):
        """
        Replaces the original closeEvent of QDialog to allow for warning to be showed and define the behaviour depending
        on why the closeEvent was triggered.

        If you click the close arrow of the Qdialog show warning. Any other trigger don't show warning.

        :param event: Event which triggered the closeEvent
        """
        if not self.finished_okay and not self.finished_on_error and not self.finished_by_user:
            message = ("If you quit now, you can use the database as is, but if you want a complete database you will "
                       "need to restart.")
            goback = self.message_window("warning", message, 2, ["Go back", "Quit"])
            
            if goback:
                event.ignore()
            else:
                self.stop_thread()
        else:
            super().closeEvent(event)
            
    def cancel_button_verification(self):
        """Checks if user really wants to cancel the ongoing scrapping."""
        message = ("If you quit now, you can use the database as is, but if you want a complete database you will need "
                   "to restart.")
        goback = self.message_window("warning", message, 2, ["Go back", "Quit"])

        if goback:
            return False
        else:
            self.stop_thread()

    def stop_thread(self):
        """Kills cmd process, interrupts and terminate the thread."""
        # Kill cmd process which is running svn list command
        try:
            if self.thread_running:
                os.kill(self.pid, signal.SIGTERM)  # Sends SIGTERM to the process
        except OSError as e:
            print(f'Error terminating process: {e}')

        # Send interruption "signal"
        self.thread.requestInterruption()

        # Terminate thread
        self.thread.quit()
        self.thread.wait()

    @Slot()
    def stop_on_task_finished(self):
        """If the SVN scrapping finishes successfully, save the result and close to return to MainWindow"""
        self.finished_okay = True
        self.close()

    @Slot(tuple)
    def stop_on_error(self, error_info: tuple):
        """Show error window and close"""
        print(error_info)
        self.finished_on_error = True

        if not self.thread.isInterruptionRequested():
            message = "Something went wrong when scrapping. Im sorry :(! Please try again."
            self.message_window("error", message)
        self.close()

    @Slot()
    def stop_on_user_interruption(self):
        """If SVN scrapping is interrupted by user save the result and close to return to MainWindow"""
        self.finished_by_user = True
        self.close()

    def message_window(self, message_type, message: str, numb_buttons=1, buttons_text: list = None) -> bool:
        """
        Creates a warning or error window wiht custom message and custom buttons.

        :param message_type: Message type (warning, error)
        :param message: Message to show user
        :param numb_buttons: value must be 1 or 2 for the number of buttons created
        :param buttons_text: text for each button created. Order of list will match order in window.
        :return: True for clicking the left button (ex: Okay) and False for clicking the "x" (to close the window) or
                 clicking the right button (ex:Cancel)
        """
        if buttons_text is None:
            buttons_text = ["Okay"]

        if numb_buttons != len(buttons_text) or numb_buttons < 1 or numb_buttons > 2:
            return False

        msg = QMessageBox(self)
        if message_type == "warning":
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Warning!")
        elif message_type == "error":
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Error!")
        else:
            return False
        msg.setText(message)

        if numb_buttons == 2:
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            button_continue = msg.button(QMessageBox.Yes)
            button_continue.setText(buttons_text[0])
            button_goback = msg.button(QMessageBox.No)
            button_goback.setText(buttons_text[1])
        elif numb_buttons == 1:
            msg.setStandardButtons(QMessageBox.Ok)
            button_ok = msg.button(QMessageBox.Ok)
            button_ok.setText(buttons_text[0])

        result = msg.exec()

        if result == QMessageBox.Yes:
            return True
        elif result == QMessageBox.No:
            return False
        elif result == QMessageBox.Ok:
            return True
