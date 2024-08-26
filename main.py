########################################################################################################################
# File info
__author__ = "João Ribas"

__license__ = "GNU GPLv3"
__version__ = "1.0"
__maintainer__ = "João Ribas"
__status__ = "Development"
""" Prototype, Development or Production """
########################################################################################################################
# Explanation:
#
# How to run:
#
# Revisions:
# V1.0 - 19/07/2024 - First release
# V1.1 - 20/08/2024 - Added thread to run svn crawler
#                   - Reorganized svn crawler to be a class
########################################################################################################################
# TODO: Add indexes after creating database or when loading a database which does not indexes.
# Todo: Add settings window
# Todo: Add logging
# Todo: Add update functionality to app so the database can be regularly updated using svn log without scrapping the
#       whole svn repo.
# Todo: Add possibility to add directories not previous available to same database.
# Todo: Add dark/white option
# Todo: Add database reindex for svn repos with high volume of files deleted\added. Database does not reuse ids so the
#       id number will increase indefinitely. Is this needed?
# Todo: Add translation
########################################################################################################################
import os
import sys
import configparser

from typing import Tuple
from natsort import os_sorted
from PySide6.QtGui import QStandardItemModel, QStandardItem, QAction, QIcon
from PySide6.QtCore import Slot, Qt, QModelIndex, QPoint, QTimer
from PySide6.QtWidgets import (QApplication, QMainWindow, QPushButton, QGridLayout, QWidget, QLabel, QLineEdit,
                               QSplitter, QTreeView, QProgressBar, QListWidget, QAbstractItemView, QMenu, QFrame,
                               QVBoxLayout, QHBoxLayout, QMessageBox, QFileDialog, QInputDialog)

from libs.repository import Repository
from libs.svn_crawler import SVNScrapper

"""
def trap_exc_during_debug(*args):
    # when app raises uncaught exception, print info
    print(args)

# install exception hook: without this, uncaught exception would cause application to exit
sys.excepthook = trap_exc_during_debug
"""


class StandardItemModel(QStandardItemModel):
    """
    Creating a custom class so the on demand treeview can work. Basically we need to specify that the treeview has
    children before lading the children. This for the "arrow" can appear before the foldername in the treeview.
    """
    ExpandableRole = Qt.UserRole + 500

    def hasChildren(self, index: QModelIndex):
        if self.data(index, StandardItemModel.ExpandableRole):
            return True
        return super(StandardItemModel, self).hasChildren(index)


class MainWindow(QMainWindow):
    """
    Main Window class based in QMainWindow of the application where all widgets will be shown.
    """

    # sig_start = Signal()  # needed only due to PyCharm debugger bug (!)
    # Script author: I didn't encounter this bug, but I will leave it here.

    def __init__(self, *args, **kwargs):
        """
        Init where all instance variables are defined.

        :param args: Arguments to pass to QMainWindow
        :param kwargs: Keyword arguments to pass to QMainWindow
        """
        super().__init__(*args, **kwargs)
        # This variable will have the Repository class to handle the database file.
        self.repo = None
        # Define the window parameters
        self.setWindowTitle('SVN Search')
        self.setWindowIcon(QIcon('icon_white.png'))
        self.setMinimumSize(400, 300)
        self.resize(1280, 720)

        # Get script\exe path
        if getattr(sys, 'frozen', False):
            self.script_path = os.path.dirname(sys.executable)
        elif __file__:
            self.script_path = os.path.dirname(os.path.abspath(__file__))

        self.config = configparser.ConfigParser()
        if os.path.exists(self.script_path + "\\config.ini"):
            self.config.read(self.script_path + "\\config.ini")
        else:
            self.create_config_file(self.script_path + "\\config.ini")

        self.repo = Repository()

        # File menu
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')

        # Add actions to the File menu
        new_action = QAction(QIcon(), 'New Database', self)
        new_action.setShortcut('Ctrl+N')
        new_action.setStatusTip('Creates a new database for a repository')
        new_action.triggered.connect(self.create_database)
        file_menu.addAction(new_action)

        load_action = QAction(QIcon(), 'Load Database', self)
        load_action.setShortcut('Ctrl+L')
        load_action.setStatusTip('Load a database from folder')
        load_action.triggered.connect(self.load_database)
        file_menu.addAction(load_action)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QGridLayout(central_widget)

        # --------------------------------------------------------------------------------------------------------------
        # Row 0 of GUI - Input line edit and "Search" button
        # --------------------------------------------------------------------------------------------------------------
        # Input widget to receive string to search for a file. Clicking enter does the same as "search_button"
        self.input_search = QLineEdit()
        self.input_search.setEnabled(False)
        self.input_search.returnPressed.connect(self.search_file)

        # Search button to find all files with string inputted
        self.search_button = QPushButton("Search")
        self.search_button.setEnabled(False)
        self.search_button.pressed.connect(self.search_file)

        # Add widgets to central widget
        #                            row, col, rowspan, colspan
        layout.addWidget(self.input_search, 0, 0, 1, 1)
        layout.addWidget(self.search_button, 0, 1, 1, 1)
        # --------------------------------------------------------------------------------------------------------------
        # Row 1 of GUI - Progress Bar
        # --------------------------------------------------------------------------------------------------------------
        # Defining progress bar to know when loading all databases and populating repo tree are done
        self.progressbar = QProgressBar()
        self.progressbar_reset()

        # Add widgets to central widget
        layout.addWidget(self.progressbar, 1, 0, 1, 2)

        # --------------------------------------------------------------------------------------------------------------
        # Row 2 of GUI (splitter)
        # --------------------------------------------------------------------------------------------------------------
        # Defining splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # -> Column 0 of splitter - repository tree
        # --------------------------------------------------------------------------------------------------------------
        # Defining frame
        repo_frame = QFrame()
        repo_layout = QVBoxLayout(repo_frame)

        # Defining label
        self.tree_repo_label = QLabel("No SVN repo loaded")
        self.tree_repo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Define tree view widget
        self.tree_repo = QTreeView()
        self.tree_repo_model = StandardItemModel()
        self.tree_repo.setHeaderHidden(True)
        self.tree_repo.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree_repo.setModel(self.tree_repo_model)
        self.tree_repo.expanded.connect(self.update_tree_repo)

        # Colapse\Expand buttons
        tree_repo_button_frame = QFrame()
        tree_repo_button_layout = QHBoxLayout(tree_repo_button_frame)

        self.tree_repo_button1 = QPushButton("Update database")
        self.tree_repo_button1.pressed.connect(self.update_database)

        tree_repo_button_layout.addWidget(self.tree_repo_button1)

        # Add widgets to layout (and to frame)
        repo_layout.addWidget(self.tree_repo_label)
        repo_layout.addWidget(self.tree_repo)
        repo_layout.addWidget(tree_repo_button_frame)

        # Add custom context menu
        self.tree_repo.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_repo.customContextMenuRequested.connect(self.show_context_menu)

        # Add frame to splitter
        self.splitter.addWidget(repo_frame)

        # -> Column 1 of splitter
        # --------------------------------------------------------------------------------------------------------------
        # Defining frame
        file_results_frame = QFrame()
        file_results_layout = QVBoxLayout(file_results_frame)

        # Defining label
        self.label2 = QLabel("File results")
        self.label2.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Defining list widget
        self.file_results = QListWidget()

        # Clear button
        file_results_button_frame = QFrame()
        file_results_button_layout = QHBoxLayout(file_results_button_frame)

        self.clear_button = QPushButton("Clear all")
        self.clear_button.pressed.connect(self.clear_list)

        file_results_button_layout.addWidget(self.clear_button)

        # Add widgets to layout (and to frame)
        file_results_layout.addWidget(self.label2)
        file_results_layout.addWidget(self.file_results)
        file_results_layout.addWidget(file_results_button_frame)

        # Add custom context menu
        self.file_results.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_results.customContextMenuRequested.connect(self.show_context_menu)
        self.file_results.itemDoubleClicked.connect(self.populate_folders_tree)

        # Add frame to splitter
        self.splitter.addWidget(file_results_frame)

        # -> Column 2 of splitter
        # --------------------------------------------------------------------------------------------------------------
        # Defining frame
        folder_results_frame = QFrame()
        folder_results_layout = QVBoxLayout(folder_results_frame)

        # Defining label
        self.label3 = QLabel("Folder results")
        self.label3.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Define tree view widget
        self.folder_results_tree = QTreeView()
        self.folder_results_tree_model = QStandardItemModel()
        self.folder_results_tree.setHeaderHidden(True)
        self.folder_results_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.folder_results_tree.doubleClicked.connect(self.show_folder_in_tree)

        # Colapse\Expand buttons
        folder_results_button_frame = QFrame()
        folder_results_button_layout = QHBoxLayout(folder_results_button_frame)

        self.folder_results_button1 = QPushButton("Colapse all")
        self.folder_results_button1.pressed.connect(lambda: self.folder_results_tree.collapseAll())

        self.folder_results_button2 = QPushButton("Expand all")
        self.folder_results_button2.pressed.connect(lambda: self.folder_results_tree.expandAll())

        folder_results_button_layout.addWidget(self.folder_results_button1)
        folder_results_button_layout.addWidget(self.folder_results_button2)

        # Add widgets to layout (and to frame)
        folder_results_layout.addWidget(self.label3)
        folder_results_layout.addWidget(self.folder_results_tree)
        folder_results_layout.addWidget(folder_results_button_frame)

        # Add frame to splitter
        self.splitter.addWidget(folder_results_frame)

        # -> Add splitter to central widget and define stretch, so it expands to fill window.
        # --------------------------------------------------------------------------------------------------------------
        layout.addWidget(self.splitter, 2, 0, 1, 2)
        layout.setRowStretch(2, 1)
        layout.setColumnStretch(0, 1)

        # Create a timer
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.load_last_db)

        # Start the timer with the desired delay (in milliseconds)
        self.timer.start(500)

    # -------------------------------------------------------------------------------------------------
    #     Startup functions
    # -------------------------------------------------------------------------------------------------
    def create_config_file(self, config_path: str):
        """Creates, if necessary the configuration file."""
        self.config["database"] = {"db_path": "", "db_name": "", "url": "", "revision": ""}
        self.config["svn_repo_scrapper"] = {"root_folder": "repo", "max_tries": "1000", "max_level": "4"}

        with open(config_path, "w") as f:
            self.config.write(f)

    def load_last_db(self):
        """Loads the last db opened if available."""
        db_path = self.config.get("database", "db_path")

        if not db_path:
            return False

        if not os.path.exists(db_path):
            self.message_window("warning", "Couldn't find the last db at this location: " + db_path)
            return False

        self.load_database(db_path, dialog=False)

    # -------------------------------------------------------------------------------------------------
    #     Config file
    # -------------------------------------------------------------------------------------------------
    def save_db_info_config_file(self):
        """Save the repository information in the config file. This enables the program to load the last opened
        database."""
        self.config.set("database", "db_path", self.repo.db_path)
        self.config.set("database", "db_name", self.repo.db_name)
        self.config.set("database", "url", self.repo.url)
        self.config.set("database", "revision", self.repo.rev)

        with open("config.ini", "w") as f:
            self.config.write(f)

    def clear_config_file(self):
        """Clear the config file due to error loading database. TODO: Check if needed."""
        self.config.set("database", "db_path", "")
        self.config.set("database", "db_name", "")
        self.config.set("database", "url", "")
        self.config.set("database", "revision", "")

        with open("config.ini", "w") as f:
            self.config.write(f)

    # -------------------------------------------------------------------------------------------------
    #     File Menu actions
    # -------------------------------------------------------------------------------------------------
    def create_database(self):
        """ Asks user for database name, url, creates the database file and scrapes the svn repo populating the
        database."""
        db_path, _ = QFileDialog.getSaveFileName(self, "Choose a name for the database file", self.script_path,
                                                 "SQlite3 (*.sqlite)")
        if not db_path:
            return False

        new_repo = Repository()
        new_repo.create_database_file(db_path)

        ok, url = self.request_repo_url()
        if not ok:
            return False

        ok, rev = self.request_repo_rev()
        if not ok:
            return False

        new_repo.save_repo_info_in_db(url, rev)

        self.progressbar.setRange(0, 0)

        scrapper = SVNScrapper(self, new_repo)
        scrapper.exec()

        if scrapper.finished_okay:
            self.repo = new_repo
            self.save_db_info_config_file()
            self.tree_repo_initialise()
            self.enable_search()

        self.progressbar_show_task_finished("Scraping was successful!")

    def request_repo_url(self):
        """Request user input for repository url"""
        ok, url = self.input_dialog("Specify the svn repository link", "Link (must be not empty):",
                                    "http://<url>.com:1111/<repository parent folder ex: repo>")

        while True:
            if not ok:
                return ok, False

            if not url:
                message = "Please do not leave the url field empty."
            elif "<url>.com:1111" in url:
                message = "Please change the provided url example."
            elif "http://" not in url and "svn://" not in url and "https://" not in url:
                message = "Please insert an url which starts with 'http://' or 'https://' or 'svn://'."
            elif "/" + self.repo.root_folder + "/" != url[len(url)-(len(self.repo.root_folder) + 2):]:
                message = ("Please insert a svn repository url which finishes with '(...)/repo/'.\nIf the svn repo "
                           "'root folder' is different please change the root folder in the setting window.")
            else:
                break

            self.message_window("warning", message)
            ok, url = self.input_dialog("Specify the svn repository link", "Link (must be not empty):",
                                        "http://<url>.com:1111/<repository parent folder ex: repo>")

        return ok, url

    def request_repo_rev(self):
        """Request user input for repository rev"""
        ok, rev = self.input_dialog("Specify a valid revision", "Revision (must be not empty):", "9999999")

        while True:
            if not ok:
                return ok, False

            try:
                _ = int(rev)
            except:
                self.message_window("warning", "Please input a valid integer.")
            else:
                if ok and (not rev or rev == "9999999"):
                    self.message_window("warning", "Please input a valid integer.")
                else:
                    break

            ok, rev = self.input_dialog("Specify a valid revision", "Revision (must be not empty):", "9999999")

        return ok, rev

    def load_database(self, db_path: str = None, dialog=True):
        """
        Requests user to select a database from dialog window, loads db info and populates tree repo treeview.

        :param db_path: If provided Dialog window will open with parent folder and start path
        :param dialog:  If True the dialog window to select database file will appear.
        """
        self.progressbar.setRange(0, 0)
        self.progressbar_update_format("Loading Database...")

        while True:
            if dialog:
                # Checks if a database is loaded and opens in that directory. If no opens in the script\exe directory.
                if self.config.get("database", "db_path"):
                    start_path = os.path.dirname(self.config.get("database", "db_path"))
                else:
                    start_path = self.script_path

                db_path, _ = QFileDialog.getOpenFileName(self, "Load database", start_path,
                                                         "SQlite3 (*.sqlite)")

            if not db_path:
                return False

            try:
                new_repo = Repository()
                new_repo.load_db_info(db_path)
                self.tree_repo_initialise(new_repo)
            except:
                self.message_window("error", "Error loading database info.")
                # This while will contoinue but now a dialog will appear for user to select new database.
                dialog = True
            else:
                self.repo = new_repo
                self.save_db_info_config_file()
                self.enable_search()
                break

        self.progressbar_show_task_finished("Database successfully loaded!")

    # -------------------------------------------------------------------------------------------------
    #     Search file
    # -------------------------------------------------------------------------------------------------
    @Slot()
    def search_file(self):
        """
        Searches for a filename in the database file using column "isfile"==1 and searching in the remaining entries
        in the column "value", and populates file results widget with results. The results will only show one instance
        of each result, even if there are duplicates.
        """
        self.progressbar.setRange(0, 0)
        # Clear results from folder results tree
        self.folder_results_tree_model.clear()

        # Get user inputted string
        query = self.input_search.text()

        # Get results from query
        results = self.repo.get_files_from_database(query)
        if results:
            files = set(result[3] for result in results)
        else:
            files = ["Couldn't find any files :("]

        # Populate file results widget
        self.populate_files_list(files)
        self.progressbar_show_task_finished("Search finished!")

    # -------------------------------------------------------------------------------------------------
    #     Tree repo widget\column
    # -------------------------------------------------------------------------------------------------
    def tree_repo_initialise(self, repo: Repository = None):
        """
        Initialises the tree_repo widget with the first item(items) from file\folder structure in the database.
        It can receive a repo which is not self.repo to check if database is okay before defining it as the repo to be
        used.
        """
        if not repo:
            repo = self.repo

        self.tree_repo_model.clear()

        root_item = repo.get_values_from_database("-1", "parentid")[0]
        children = repo.get_values_from_database(root_item[0], "parentid")

        tree_item_text = QStandardItem(root_item[3])
        tree_item_id = QStandardItem(str(root_item[0]))

        if children:
            tree_item_text.setData(True, StandardItemModel.ExpandableRole)

        self.tree_repo_model.appendRow([tree_item_text, tree_item_id])
        self.tree_repo.setColumnHidden(1, True)

        self.tree_repo_label.setText("SVN repo: %s" % repo.url)

    @Slot(QModelIndex)
    def update_tree_repo(self, index: QModelIndex):
        """
        Function which is called to make the on demand treeview work. Receives the item index, gets all its children
        from the database, check if te children have children and updates the treeview.

        :param index: Index of the item clicked
        """
        row = index.row()
        parent = self.tree_repo_model.itemFromIndex(index.parent())

        if parent:
            item = parent.child(row)
            item_id = parent.child(row, 1).text()
        else:
            item = self.tree_repo_model.item(row)
            item_id = self.tree_repo_model.item(row, 1).text()

        if not item.rowCount():
            childs = self.repo.get_values_from_database(item_id, "parentid")

            for child_id, _, isfile, value in childs:
                child_item_text = QStandardItem(value)
                child_item_id = QStandardItem(str(child_id))
                child_childs = self.repo.get_values_from_database(child_id, "parentid")
                if child_childs:
                    child_item_text.setData(True, StandardItemModel.ExpandableRole)

                item.appendRow([child_item_text, child_item_id])

        self.tree_repo.resizeColumnToContents(0)
        self.tree_repo.setColumnHidden(1, True)

    @Slot(QModelIndex)
    def show_folder_in_tree(self, item_index: QModelIndex):
        """
        Grabs tree item clicked in the folder results tree and expands the repo tree to show it.

        :param item_index: index of the item clicked.
        """
        filename = self.folder_results_tree_model.itemFromIndex(item_index).text()
        parent = self.folder_results_tree_model.itemFromIndex(item_index).parent()
        if not parent:
            return False
        filepath_parts = [filename, parent.text()]

        while True:
            try:
                parent = parent.parent()
                filepath_parts.append(parent.text())
            except AttributeError:
                break

        filepath_parts = filepath_parts[::-1]

        item = self.tree_repo_model.invisibleRootItem()
        index = self.tree_repo_model.indexFromItem(item)
        item_to_expand = self.tree_repo_model.invisibleRootItem()
        for part in filepath_parts:
            child_count = item_to_expand.rowCount()
            for row in range(child_count):
                item = item_to_expand.child(row)
                item_text = item.text()
                if item_text == part:
                    item_to_expand = item
                    index = self.tree_repo_model.indexFromItem(item)
                    self.tree_repo.expand(index)
                    break

        self.tree_repo.setCurrentIndex(index)
        self.tree_repo.scrollTo(index)

    def update_database(self):
        pass

    # -------------------------------------------------------------------------------------------------
    #     File results list widget\column
    # -------------------------------------------------------------------------------------------------
    def populate_files_list(self, files: list):
        """
        Populates file results widget with results.

        :param files: List of filenames found using user inputted query
        """
        self.file_results.clear()
        for file in os_sorted(files):
            self.file_results.addItem(file)

    def clear_list(self):
        """Clear file and folders results"""
        self.file_results.clear()
        self.folder_results_tree_model.clear()

    # -------------------------------------------------------------------------------------------------
    #     Folder results treeview widget\column
    # -------------------------------------------------------------------------------------------------
    @Slot(QStandardItem)
    def populate_folders_tree(self, list_item: QStandardItem):
        """
        Gets sender widget item text, finds which folders the item is and populates folders tree view with structure
        for this specific locations.

        :param list_item: List item which was clicked
        """
        if list_item.text() == "Couldn't find any files :(":
            return False

        self.progressbar_update_format("Loading folders tree: %p%")
        # Get all rows from db with file clicked as the value
        file_intances = self.repo.get_values_from_database(list_item.text(), "value")

        structure = {}
        files_done_count = 0
        for row_id, parent_id, isfile, filename in file_intances:
            folders_file_family = [filename]
            # Get all parents from db
            while parent_id != -1:
                _, parent_id, _, folder_name = self.repo.get_values_from_database(parent_id, "id")[0]
                folders_file_family.append(folder_name)

            files_done_count += 1
            percentage = int((files_done_count / len(file_intances)) * 100)
            self.progressbar_update_value(percentage)
            app.processEvents()

            folders_file_family = folders_file_family[::-1]
            temp_structure = structure
            for item in folders_file_family:
                if item not in temp_structure.keys():
                    temp_structure[item] = {}
                temp_structure = temp_structure[item]

        self.folder_results_tree_model.clear()
        self.populate_tree(self.folder_results_tree, self.folder_results_tree_model, structure)
        self.folder_results_tree.expandAll()

        self.progressbar_show_task_finished("Folder tree successfully created!")

    def populate_tree(self, tree: QTreeView, tree_model: QStandardItemModel, structure: dict):
        """
        Populates the folders tree widget with a structure file folder structure and displays it.

        :param tree: Tree GUI object to set model
        :param tree_model: Model to insert in the Tree GUI widget
        :param structure: Structure in format of a dictionary which simulates the tree structure
        """

        # Finds root item from structure and inserts in tree view model
        root_item = list(structure.keys())[0]
        tree_model.appendRow([QStandardItem(root_item)])

        counter = 1
        # Initialize stack, to avoid using recursive functions as the script sometimes reaches the system limit
        stack = [(tree_model.item(0), structure[root_item])]
        # Cycle through all keys and values from structure and create the necessary items for tree view.
        while stack:
            current_parent, current_data = stack.pop()
            for key, value in current_data.items():
                if key == "_files":
                    for file_name in value:
                        file_item = QStandardItem(file_name)
                        current_parent.appendRow(file_item)

                        counter += 1
                else:
                    folder_item = QStandardItem(key)
                    current_parent.appendRow(folder_item)
                    stack.append((folder_item, value))

        # Set model to widget (shows data)
        tree.setModel(tree_model)

    # -------------------------------------------------------------------------------------------------
    #     Context menu
    # -------------------------------------------------------------------------------------------------
    def show_context_menu(self, pos: QPoint):
        """
        Shows context menu when right-clicking left or middle column of splitter. Connects functions
        "set_input_search_text".

        :param pos: Position of the mouse
        """
        # Determine the sender widget
        sender_widget = self.sender()

        # Create context menu
        context_menu = QMenu(self)
        action_set_text = QAction("Move to search", self)

        # Connect action to slot with an additional argument for the sender
        action_set_text.triggered.connect(lambda: self.set_input_search_text(pos, sender_widget))
        context_menu.addAction(action_set_text)

        # Use the sender to decide where to map the global position
        if sender_widget == self.tree_repo:
            context_menu.exec(self.tree_repo.mapToGlobal(pos))
        elif sender_widget == self.file_results:
            context_menu.exec(self.file_results.mapToGlobal(pos))

    def set_input_search_text(self, pos: QPoint, sender_widget: QWidget):
        """
        Gets tree item\\list item text and input its to input line edit widget.

        :param pos: Position of the mouse
        :param sender_widget: Widget which sent the request for context menu
        """
        item_text = ""
        # Find which widget requested the context menu and get item text.
        if sender_widget == self.tree_repo:
            index = self.tree_repo.indexAt(pos)
            if index.isValid():
                item_text = self.tree_repo_model.itemFromIndex(index)
        elif sender_widget == self.file_results:
            item_text = self.file_results.itemAt(pos)

        # If no text is found do nothing.
        if item_text:
            self.input_search.setText(item_text.text())

    # -------------------------------------------------------------------------------------------------
    #     Top Level windows
    # -------------------------------------------------------------------------------------------------
    def input_dialog(self, window_title: str, label_text: str, text_value: str) -> Tuple[int, str]:
        """
        Creates an inpt dialog window to receive the input from the user.

        :param window_title: title of the input dialog
        :param label_text: text to be displayed right on top of the Input boc
        :param text_value: text to be diplayed on the input box as default
        :return: Tuple[bool, str] -> ok: if user clicked the okay button, url: text in the Input box.
        """
        dlg = QInputDialog(self)
        dlg.setInputMode(QInputDialog.TextInput)
        dlg.setWindowTitle(window_title)
        dlg.setLabelText(label_text)
        dlg.setTextValue(text_value)
        dlg.resize(400, 100)
        ok = dlg.exec()
        url = dlg.textValue()

        return ok, url

    def message_window(self, message_type, message: str, numb_buttons=1, buttons_text: list = None) -> bool:
        """
        Creates a warning or error window with custom message and custom buttons.

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
            button_ok.setText("Okay")

        result = msg.exec()

        if result == QMessageBox.Yes:
            return True
        elif result == QMessageBox.No:
            return False
        elif result == QMessageBox.Ok:
            return True

    # -------------------------------------------------------------------------------------------------
    #     Support functions
    # -------------------------------------------------------------------------------------------------
    def enable_search(self):
        """Enables search by the enter and search button"""
        self.input_search.setEnabled(True)
        self.search_button.setEnabled(True)

    @Slot(int)
    def progressbar_update_value(self, percentage: int):
        """
        Update progress bar value.

        :param percentage: New value to update progressbar
        """
        self.progressbar.setValue(percentage)

    @Slot(str)
    def progressbar_update_format(self, pg_format: str):
        """
        Update progress bar format string.

        :param pg_format: New string for progressbar format
        """
        self.progressbar.setFormat(pg_format)

    def progressbar_show_task_finished(self, message):
        """Shows progress bar at 100 during 1.5s and then resets it"""
        self.progressbar.setRange(0, 100)
        self.progressbar.setValue(100)
        self.progressbar.setFormat(message)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.progressbar_reset)

        self.timer.start(1500)

    @Slot()
    def progressbar_reset(self):
        """Resets the progressbar to range of 0, 100, value 0 and format to "Waiting for tasks"."""
        self.progressbar.setRange(0, 100)
        self.progressbar.setValue(0)
        self.progressbar.setFormat("Waiting for tasks...")


if __name__ == "__main__":
    app = QApplication(['-platform', 'windows:darkmode=2'])
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
