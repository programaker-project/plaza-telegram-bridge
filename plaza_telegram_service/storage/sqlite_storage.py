import os
import sqlite3
from xdg import XDG_DATA_HOME

DB_PATH_ENV = 'PLAZA_TELEGRAM_BRIDGE_DB_PATH'
if os.getenv(DB_PATH_ENV, None) is None:
    DATA_DIRECTORY = os.path.join(XDG_DATA_HOME, 'plaza', 'bridges', 'telegram')
    DEFAULT_PATH = os.path.join(DATA_DIRECTORY, 'db.sqlite3')
else:
    DEFAULT_PATH = os.getenv(DB_PATH_ENV)
    DATA_DIRECTORY = os.path.dirname(DEFAULT_PATH)


class DBContext:
    def __init__(self, db, close_on_exit=True):
        self.db = db
        self.close_on_exit = close_on_exit

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc_value, tb):
        if self.close_on_exit:
            self.db.close()


class SqliteStorage:
    def __init__(self, path, multithread=True):
        self.path = path
        self.db = None
        self.multithread = multithread
        self._create_db_if_not_exists()

    def _open_db(self):
        if not self.multithread:
            if self.db is None:
                self.db = sqlite3.connect(self.path)
                self.db.execute('PRAGMA foreign_keys = ON;')
            db = self.db
        else:
            db = sqlite3.connect(self.path)
            db.execute('PRAGMA foreign_keys = ON;')

        return DBContext(db, close_on_exit=not self.multithread)

    def _create_db_if_not_exists(self):
        os.makedirs(DATA_DIRECTORY, exist_ok=True)
        with self._open_db() as db:
            c = db.cursor()
            c.execute('''
            CREATE TABLE IF NOT EXISTS TELEGRAM_USERS (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id VARCHAR(256) UNIQUE
            );
            ''')

            c.execute('''
            CREATE TABLE IF NOT EXISTS TELEGRAM_ROOMS (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_room_id VARCHAR(256) UNIQUE,
                room_name text
            );
            ''')

            c.execute('''
            CREATE TABLE IF NOT EXISTS TELEGRAM_USERS_IN_ROOMS (
                telegram_id INTEGER,
                room_id INTEGER,
                UNIQUE(telegram_id, room_id),
                FOREIGN KEY(telegram_id) REFERENCES TELEGRAM_USERS(id),
                FOREIGN KEY(room_id) REFERENCES TELEGRAM_ROOMS(id)
            );
            ''')

            c.execute('''
            CREATE TABLE IF NOT EXISTS PLAZA_USERS (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plaza_user_id VARCHAR(36) UNIQUE
            );
            ''')

            c.execute('''
            CREATE TABLE IF NOT EXISTS PLAZA_USERS_IN_TELEGRAM (
                plaza_id INTEGER,
                telegram_id INTEGER,
                UNIQUE(plaza_id, telegram_id),
                FOREIGN KEY(plaza_id) REFERENCES PLAZA_USERS(id),
                FOREIGN KEY(telegram_id) REFERENCES TELEGRAM_USERS(id)
            );
            ''')
            db.commit()
            c.close()

    def is_telegram_user_registered(self, user_id):
        with self._open_db() as db:
            c = db.cursor()
            c.execute('''
            SELECT count(1)
            FROM TELEGRAM_USERS
            WHERE telegram_user_id=?
            ;
            ''', (user_id,))
            result = c.fetchone()[0]

            c.close()

            return result > 0

    def get_plaza_user_from_telegram(self, user_id):
        with self._open_db() as db:
            c = db.cursor()
            c.execute('''
            SELECT plaza_user_id
            FROM PLAZA_USERS as p
            JOIN PLAZA_USERS_IN_TELEGRAM as puit
            ON puit.plaza_id = p.id
            JOIN TELEGRAM_USERS as t
            ON puit.telegram_id = t.id
            WHERE t.telegram_user_id=?
            ;
            ''', (user_id,))
            results = c.fetchall()

            c.close()
            assert 0 <= len(results) <= 1
            if len(results) == 0:
                raise Exception('User (telegram:{}) not found'.format(user_id))
            return results[0][0]

    def _get_or_add_telegram_user(self, cursor, telegram_user):
        cursor.execute('''
        SELECT id
        FROM TELEGRAM_USERS
        WHERE telegram_user_id=?
        ;
        ''', (telegram_user,))

        results = cursor.fetchall()
        if len(results) == 0:  # New user
            cursor.execute('''
            INSERT INTO TELEGRAM_USERS (telegram_user_id) VALUES(?);
            ''', (telegram_user,))
            return cursor.lastrowid
        elif len(results) == 1:  # Existing user
            return results[0][0]
        else:  # This shouldn't happen
            raise Exception(
                'Integrity error, query by UNIQUE returned multiple values: {}'
                .format(cursor.rowcount))

    def _get_or_add_telegram_room(self, cursor, telegram_room, room_name):
        cursor.execute('''
        SELECT id
        FROM TELEGRAM_ROOMS
        WHERE telegram_room_id=?
        ;
        ''', (telegram_room,))

        results = cursor.fetchall()
        if len(results) == 0:  # New user
            cursor.execute('''
            INSERT INTO TELEGRAM_ROOMS (telegram_room_id, room_name) VALUES(?, ?);
            ''', (telegram_room, room_name))
            return cursor.lastrowid
        elif len(results) == 1:  # Existing user
            return results[0][0]
        else:  # This shouldn't happen
            raise Exception(
                'Integrity error, query by UNIQUE returned multiple values: {}'
                .format(cursor.rowcount))

    def _get_or_add_plaza_user(self, cursor, plaza_user):
        cursor.execute('''
        SELECT id
        FROM PLAZA_USERS
        WHERE plaza_user_id=?
        ;
        ''', (plaza_user,))

        results = cursor.fetchall()
        if len(results) == 0:  # New user
            cursor.execute('''
            INSERT INTO PLAZA_USERS (plaza_user_id) VALUES(?);
            ''', (plaza_user,))
            return cursor.lastrowid
        elif len(results) == 1:  # Existing user
            return results[0][0]
        else:  # This shouldn't happen
            raise Exception(
                'Integrity error, query by UNIQUE returned multiple values: {}'
                .format(cursor.rowcount))

    def register_user(self, telegram_user, plaza_user):
        with self._open_db() as db:
            c = db.cursor()
            telegram_id = self._get_or_add_telegram_user(c, telegram_user)
            plaza_id = self._get_or_add_plaza_user(c, plaza_user)
            c.execute('''
            INSERT OR REPLACE INTO
            PLAZA_USERS_IN_TELEGRAM (plaza_id, telegram_id)
            VALUES (?, ?)
            ''', (plaza_id, telegram_id))
            c.close()
            db.commit()

    def add_user_to_room(self, telegram_user, telegram_room, room_name):
        with self._open_db() as db:
            c = db.cursor()
            telegram_id = self._get_or_add_telegram_user(c, telegram_user)
            room_id = self._get_or_add_telegram_room(c, telegram_room, room_name)
            c.execute('''
            INSERT OR REPLACE INTO
            TELEGRAM_USERS_IN_ROOMS (telegram_id, room_id)
            VALUES (?, ?)
            ''', (telegram_id, room_id))
            c.close()
            db.commit()

    def get_telegram_users(self, plaza_user):
        with self._open_db() as db:
            c = db.cursor()
            plaza_id = self._get_or_add_plaza_user(c, plaza_user)
            c.execute('''
            SELECT telegram_user_id
            FROM TELEGRAM_USERS t
            JOIN PLAZA_USERS_IN_TELEGRAM p_in_t
            ON t.id=p_in_t.telegram_id
            WHERE p_in_t.plaza_id=?
            ;
            ''', (plaza_id,))
            results = c.fetchall()
            c.close()
            return [row[0] for row in results]

    def get_telegram_rooms_for_plaza_user(self, plaza_user):
        with self._open_db() as db:
            c = db.cursor()
            plaza_id = self._get_or_add_plaza_user(c, plaza_user)
            c.execute('''
            SELECT t_users.telegram_user_id, t_rooms.telegram_room_id, t_rooms.room_name
            FROM TELEGRAM_USERS t_users
            JOIN PLAZA_USERS_IN_TELEGRAM p_in_t
            ON t_users.id=p_in_t.telegram_id
            JOIN TELEGRAM_USERS_IN_ROOMS tu_in_rooms
            on t_users.id=tu_in_rooms.telegram_id
            JOIN TELEGRAM_ROOMS t_rooms
            on tu_in_rooms.room_id=t_rooms.id
            WHERE p_in_t.plaza_id=?
            ;
            ''', (plaza_id,))
            results = c.fetchall()
            c.close()
            return results

def get_default():
    return SqliteStorage(DEFAULT_PATH)