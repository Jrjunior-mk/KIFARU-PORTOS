import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// A cached JSON value with the time it was stored (for "last updated" age).
class CachedValue<T> {
  const CachedValue(this.value, this.storedAt);
  final T value;
  final DateTime storedAt;
  Duration get age => DateTime.now().difference(storedAt);
}

/// Minimal JSON cache on top of shared_preferences.
///
/// Every entry is stored as `{"at": <iso>, "v": <json>}` so callers can show
/// how stale offline data is.
class LocalCache {
  LocalCache(this.prefs);
  final SharedPreferences prefs;

  static const _prefix = 'kifaru.cache.';

  Future<void> putJson(String key, Object? value) async {
    await prefs.setString(
      '$_prefix$key',
      jsonEncode({'at': DateTime.now().toIso8601String(), 'v': value}),
    );
  }

  CachedValue<T>? getJson<T>(String key, T Function(Object json) parse) {
    final s = prefs.getString('$_prefix$key');
    if (s == null) return null;
    try {
      final m = jsonDecode(s);
      if (m is! Map) return null;
      final at =
          DateTime.tryParse(m['at']?.toString() ?? '') ?? DateTime.now();
      final v = m['v'];
      if (v == null) return null;
      return CachedValue<T>(parse(v), at);
    } catch (_) {
      return null;
    }
  }

  Future<void> remove(String key) => prefs.remove('$_prefix$key');

  Future<void> clearAll() async {
    for (final k in prefs.getKeys().where((k) => k.startsWith(_prefix))) {
      await prefs.remove(k);
    }
  }
}
