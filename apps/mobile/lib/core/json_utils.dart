/// Small, defensive JSON helpers shared by every model.
///
/// The API stores timestamps in UTC. SQLite-backed dev servers may emit naive
/// ISO strings (no `Z`); those are interpreted as UTC, never as device-local.
library;

DateTime? parseUtc(Object? v) {
  if (v == null) return null;
  final s = v.toString();
  final dt = DateTime.tryParse(s);
  if (dt == null) return null;
  if (dt.isUtc) return dt;
  final hasOffset = RegExp(r'(Z|[+-]\d{2}:?\d{2})$').hasMatch(s);
  if (hasOffset) return dt.toUtc();
  return DateTime.utc(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
      dt.millisecond, dt.microsecond);
}

int? asInt(Object? v) {
  if (v == null) return null;
  if (v is num) return v.toInt();
  return int.tryParse(v.toString());
}

double? asDouble(Object? v) {
  if (v == null) return null;
  if (v is num) return v.toDouble();
  return double.tryParse(v.toString());
}

bool asBool(Object? v, {bool fallback = false}) {
  if (v is bool) return v;
  if (v is String) return v.toLowerCase() == 'true';
  return fallback;
}

String? asString(Object? v) => v?.toString();

List<String> asStringList(Object? v) =>
    v is List ? v.map((e) => e.toString()).toList() : const <String>[];

Map<String, dynamic> asMap(Object? v) =>
    v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

List<Map<String, dynamic>> asMapList(Object? v) => v is List
    ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList()
    : const <Map<String, dynamic>>[];

List<dynamic> asList(Object? v) => v is List ? v : const <dynamic>[];
