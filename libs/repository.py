import os
import sys
import sqlite3
import subprocess
import configparser

from lxml import etree
from pathlib import Path
from typing import Tuple, List


class CustomException(Exception):
    """Custom exceptions"""
    pass


class Repository(object):
    """
    Class to handle all operations related to the database
    """
    def __init__(self):
        self.db_path = None
        self.db_name = None
        self.url = None
        self.rev = None
        self.root_folder = None
        self.max_tries = None
        self.max_level = None

        if getattr(sys, 'frozen', False):
            self.script_path = Path(os.path.dirname(sys.executable))
        elif __file__:
            self.script_path = Path(os.path.dirname(os.path.abspath(__file__)))
        else:
            raise CustomException("Error! Couldn't find the script path.")

        self.config = configparser.ConfigParser()
        self.config.read(self.script_path.parent.joinpath("config.ini"))

        self.load_config()

    def load_db_info(self, db_path: str):
        """
        Retrieves the db info from the database

        :param db_path: It can receive a custom db_path because we want to check if database is okay before loading it
                        permanently
        """
        self.db_path = db_path
        _, self.db_name, self.url, self.rev = self.get_values_from_database("1", "id", "repository_info", db_path)[0]

    def load_config(self):
        """Retrieves the svn scrapper configuration"""
        self.root_folder = self.config.get("svn_repo_scrapper", "root_folder")
        self.max_tries = self.config.get("svn_repo_scrapper", "max_tries")
        self.max_level = int(self.config.get("svn_repo_scrapper", "max_level"))

    def create_database_file(self, db_path: str):
        """
        Creates the database file using filepath as the path and filename to use. The database will have two tables with
        the following columns:

        - First table: repository

        +------------------+----------+--------+--------+
        | id (primary key) | parentid | isfile | value  |
        +==================+==========+========+========+
        |         1        |    -1    |    0   |  repo  |
        |         2        |     1    |    1   | ola.py |
        +------------------+----------+--------+--------+

        - Second table: repository_info

        +------------------+---------+--------------------------------+----------+
        | id (primary key) | name    |             url                | revision |
        +==================+=========+================================+==========+
        |        1         | test_db | http://test_db.com:23432/repo/ |   1111   |
        +------------------+---------+--------------------------------+----------+
        """
        self.db_path = db_path

        if os.path.exists(self.db_path):
            os.remove(self.db_path)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE repository (
                            id INTEGER PRIMARY KEY,
                            parentid INTEGER NOT NULL,
                            isfile INTEGER NOT NULL,
                            value TEXT NOT NULL)''')
        cursor.execute('''CREATE TABLE repository_info (
                            id	INTEGER PRIMARY KEY,
                            name TEXT NOT NULL,
                            url TEXT NOT NULL,
                            revision TEXT NOT NULL)''')

        conn.commit()
        conn.close()

    def save_repo_info_in_db(self, url: str, rev: str):
        """
        Saves the db info in the class and to the database file

        :param url: SVN repository url
        :param rev: SVN repository information current revision
        """
        self.url = url
        self.rev = rev
        self.db_name = self.db_path.split("/")[-1].replace(".sqlite", "")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''INSERT INTO repository_info (id, name, url, revision) 
                          VALUES (?, ?, ?, ?)''', (1, self.db_name, self.url, self.rev))

        conn.commit()
        conn.close()

    def get_files_from_database(self, search_value: str) -> List[Tuple]:
        """
        Retrieves all rows from table "repository" where column "isfile" is 1 and the search value matches any part of
        the string of the column "Value".

        :param search_value: Value to be used as search value in column "Value"
        :return: Returns the row(rows) as list of tuples. Each tuple is a row containing values from all columns.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = f"SELECT * FROM repository WHERE isfile = 1 AND value LIKE ?"
        cursor.execute(query, ("%" + search_value + "%",))
        root_item = cursor.fetchall()

        cursor.close()
        conn.close()

        return root_item

    def get_values_from_database(self, search_value: str, column: str, table="repository", db_path=None) -> List[Tuple]:
        """
        Retrieves values from the database based on the parameters provided.

        :param search_value: Value to be used as search value
        :param column: Column to search the value
        :param table: Table to search the value
        :param db_path: If not provided will be self.db_path
        :return: Returns the row(rows) as list of tuples. Each tuple is a row containing values from all columns.
        """
        if not db_path:
            db_path = self.db_path

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        query = f"SELECT * FROM {table} WHERE {column} IS ?"
        cursor.execute(query, (search_value,))
        root_item = cursor.fetchall()

        cursor.close()
        conn.close()

        return root_item

    def add_values_to_database(self, data: list[tuple]):
        """
        TODO: NOT TESTED!
        Adds all rows provided in data to the table repository.

        :param data: List of tuples. Each tuple has all information to add to a row of the database
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for row_id, parent_id, isfile, value in data:
            cursor.execute('''INSERT INTO repository (id, parentid, file, value) 
                              VALUES (?, ?, ?, ?)''', (row_id, parent_id, isfile, value))

        conn.commit()
        conn.close()

    def rem_values_from_database(self, ids: list):
        """
        TODO: NOT TESTED!
        Removes all rows which match the ids provided.

        :param ids: List of id's to be removed.
        :return:
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for row_id in ids:
            cursor.execute('''DELETE FROM repository WHERE id = ?''', (row_id,))

        conn.commit()
        conn.close()

    def get_log(self, final_rev=""):
        """
        TODO: NOT TESTED!
        Retrieves the log from the revision saved in the db to the last revision available or the one specified.

        :param final_rev: final revision to use when updating the db
        :return: Returns output of the command
        """
        if not final_rev:
            final_rev = "HEAD"
        data = subprocess.run(['svn', 'log', "--verbose", '--xml', '-r', self.rev + ':' + final_rev, self.url],
                              capture_output=True)

        if data and data.returncode == 0:
            print("Getting log from %s to %s was successful!" % (self.rev, final_rev))
        else:
            print("Error: Getting log from %s to %s was unsuccessful!" % (self.rev, final_rev))
            print(str(data.stderr))
            return False

        parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, resolve_entities=False)
        vcdl_tree = etree.fromstring(data.stdout, parser=parser)
        root = vcdl_tree.getroot()

        return root

    def update_database(self):
        """
        TODO: NOT TESTED!
        Analyzes the svn log output and updates the database.
        """
        root = self.get_log(self.url)
        path_elements = root.xpath("//path")

        for element in path_elements:
            action = element.attrib["action"]
            item_kind = element.attrib["kind"]

            if action == "A":
                self.action_add(element, item_kind)
            elif action == "D":
                self.action_delete(element, item_kind)

        return None

    def action_add(self, element, item_kind):
        """
        TODO: NOT TESTED!
        If action is copy from or just adding a file this function is called.

        :param element: xml element with filepath
        :param item_kind: file or folder
        """
        # Removes "/" at the beginning and replaces / for \
        # Removes "amp;" which svn add because of space in folder\file name
        item_path = element.text[1::].replace("/", "\\").replace("amp;", "")

        if item_kind == "file":
            try:
                copy_from = element.attrib["copyfrom-path"][1::].replace("/", "\\")
                copy_from.replace("amp;", "")
                self.add_file(item_path)

            except KeyError:
                pass

    def action_delete(self, element, item_kind):
        """
        TODO: NOT TESTED!
        If action is delete\\remove a file this function is called.

        :param element: xml element with filepath
        :param item_kind: file or folder
        """
        # Removes "/" at the beginning and replaces / for \
        # Removes "amp;" which svn add because of space in folder\file name
        filepath = element.text[1::].replace("/", "\\").replace("amp;", "")

        try:
            copy_from = element.attrib["copyfrom-path"][1::].replace("/", "\\")
            copy_from.replace("amp;", "")

            if item_kind == "file":
                self.add_file(filepath)

        except:
            print(element.text)

    def add_file(self, filepath):
        pass

