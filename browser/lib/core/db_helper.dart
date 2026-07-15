import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import 'package:shared_preferences/shared_preferences.dart';

class DbHelper {
  static Database? _database;

  static Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDatabase();
    return _database!;
  }

  static Future<Database> _initDatabase() async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, 'feedo_browser.db');

    return await openDatabase(
      path,
      version: 1,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            title TEXT,
            timestamp INTEGER
          )
        ''');
        await db.execute('''
          CREATE TABLE bookmarks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            title TEXT,
            timestamp INTEGER
          )
        ''');
      },
    );
  }

  static Future<void> addHistory(String url, String title) async {
    final db = await database;
    // Delete existing entry for the same URL to avoid duplicates
    await db.delete('history', where: 'url = ?', whereArgs: [url]);
    await db.insert(
      'history',
      {
        'url': url,
        'title': title,
        'timestamp': DateTime.now().millisecondsSinceEpoch,
      },
    );
  }

  static Future<List<Map<String, dynamic>>> getHistory() async {
    final db = await database;
    return await db.query('history', orderBy: 'timestamp DESC');
  }

  static Future<void> addBookmark(String url, String title) async {
    final db = await database;
    // Delete existing entry for the same URL to avoid duplicates
    await db.delete('bookmarks', where: 'url = ?', whereArgs: [url]);
    await db.insert(
      'bookmarks',
      {
        'url': url,
        'title': title,
        'timestamp': DateTime.now().millisecondsSinceEpoch,
      },
    );
  }

  static Future<List<Map<String, dynamic>>> getBookmarks() async {
    final db = await database;
    return await db.query('bookmarks', orderBy: 'timestamp DESC');
  }

  static Future<void> clearAll() async {
    // Clear SQLite tables
    final db = await database;
    await db.execute('DELETE FROM history');
    await db.execute('DELETE FROM bookmarks');
    // Clear SharedPreferences (My Sites / published domains)
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('my_domains');
  }
}
