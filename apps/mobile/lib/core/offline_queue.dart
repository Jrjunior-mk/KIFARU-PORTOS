import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'api_exceptions.dart';

class PositionSample {
  const PositionSample({
    required this.vehicleId,
    required this.lat,
    required this.lon,
    required this.at,
  });

  factory PositionSample.fromJson(Map<String, dynamic> j) => PositionSample(
        vehicleId: j['vehicle_id'].toString(),
        lat: (j['lat'] as num).toDouble(),
        lon: (j['lon'] as num).toDouble(),
        at: DateTime.parse(j['at'].toString()),
      );

  final String vehicleId;
  final double lat;
  final double lon;
  final DateTime at;

  Map<String, dynamic> toJson() => {
        'vehicle_id': vehicleId,
        'lat': lat,
        'lon': lon,
        'at': at.toIso8601String(),
      };
}

/// Store-and-forward queue for `POST /fleet/vehicles/{id}/position`.
///
/// When the phone has no connectivity the driver app keeps sampling GPS; the
/// samples are persisted here and flushed in order once a request succeeds.
/// Capped at [maxItems]; the API keeps only the last position anyway, so the
/// oldest entries are dropped first.
class PositionQueue {
  PositionQueue(this._prefs);
  final SharedPreferences _prefs;

  static const _key = 'kifaru.position_queue';
  static const maxItems = 120;

  List<PositionSample> _read() {
    final s = _prefs.getString(_key);
    if (s == null) return [];
    try {
      final l = jsonDecode(s);
      if (l is! List) return [];
      return l
          .whereType<Map>()
          .map((e) => PositionSample.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> _write(List<PositionSample> items) => _prefs.setString(
      _key, jsonEncode(items.map((e) => e.toJson()).toList()));

  int get length => _read().length;

  Future<void> enqueue(PositionSample s) async {
    final items = _read()..add(s);
    while (items.length > maxItems) {
      items.removeAt(0);
    }
    await _write(items);
  }

  /// Posts queued samples oldest-first. Stops at the first network failure
  /// (leaving the rest queued); drops samples the server rejects (4xx).
  Future<int> flush(ApiClient api) async {
    final items = _read();
    var sent = 0;
    while (items.isNotEmpty) {
      final s = items.first;
      try {
        await api.post('/fleet/vehicles/${s.vehicleId}/position',
            body: {'lat': s.lat, 'lon': s.lon});
        sent++;
        items.removeAt(0);
      } on NetworkException {
        break;
      } on ApiException {
        items.removeAt(0);
      }
    }
    await _write(items);
    return sent;
  }

  Future<void> clear() => _prefs.remove(_key);
}
