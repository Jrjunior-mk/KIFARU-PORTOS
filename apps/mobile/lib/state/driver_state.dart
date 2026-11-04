import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:geolocator/geolocator.dart';

import '../core/api_client.dart';
import '../core/api_exceptions.dart';
import '../core/cache.dart';
import '../core/decision_instruction.dart';
import '../core/json_utils.dart';
import '../core/offline_queue.dart';
import '../core/ws_client.dart';
import '../l10n/strings.dart';
import '../models/appointment.dart';
import '../models/station.dart';
import '../models/vehicle.dart';
import '../models/weighing_event.dart';
import 'app_settings.dart';

/// Everything the Driver Mode screen shows, for one selected [vehicle].
///
/// Data sources (all read-only from the driver's point of view):
/// * `GET /queue/appointments/mine`  -> active appointment for this vehicle
/// * `GET /stations/{id}`            -> queue length / wait / static lane
/// * `GET /weighing/events?vehicle_id=&limit=1` -> latest decision + ticket
/// * `ws://.../ws/events?types=clearance.decided,queue.updated` -> push
///   (polling every [AppSettings.driverPollInterval] as fallback)
/// * `POST /fleet/vehicles/{id}/position` every 60 s (queued when offline)
class DriverState extends ChangeNotifier {
  DriverState({
    required this.api,
    required this.cache,
    required this.settings,
    required this.vehicle,
    FlutterTts? tts,
  })  : _tts = tts,
        _posQueue = PositionQueue(cache.prefs);

  final ApiClient api;
  final LocalCache cache;
  final AppSettings settings;
  final Vehicle vehicle;

  static const positionInterval = Duration(seconds: 60);
  static const speakIfYoungerThan = Duration(minutes: 30);

  Appointment? appointment;
  Station? station;
  WeighingEvent? latest;
  DateTime? lastUpdated;
  bool offline = false;
  bool fromCache = false;
  bool wsConnected = false;
  String? error;

  /// `idle | sent | queued | denied | error`
  String gpsStatus = 'idle';
  int queuedPositions = 0;
  DateTime now = DateTime.now().toUtc();

  WsClient? _ws;
  StreamSubscription<WsEvent>? _wsSub;
  Timer? _poll;
  Timer? _gps;
  Timer? _tick;
  FlutterTts? _tts;
  final PositionQueue _posQueue;
  String? _spokenDecisionId;
  bool _refreshing = false;
  bool _disposed = false;

  String get _cacheKey => 'driver.${vehicle.id}';

  Decision? get decision => latest?.decision;

  /// The static lane only applies when the station we know about is the one
  /// where the latest pass happened.
  Instruction get instruction => instructionFor(
        decision?.decision,
        staticLaneNo:
            (station != null && station!.id == latest?.stationId) ? station!.staticLaneNo : null,
      );

  Duration? get untilSlot =>
      appointment == null ? null : appointment!.slotStart.difference(now);

  // ------------------------------------------------------------------ lifecycle
  Future<void> start() async {
    _loadCache();
    notifyListeners();
    await refreshAll();

    _ws = WsClient(urlBuilder: () async {
      final t = api.accessToken;
      if (t == null) return null;
      return api.wsUri(t, types: const ['clearance.decided', 'queue.updated']);
    });
    _ws!.connected.addListener(_onWsStatus);
    _wsSub = _ws!.events.listen(_onWsEvent);
    unawaited(_ws!.connect());

    _poll = Timer.periodic(settings.driverPollInterval, (_) => refreshAll());
    _gps = Timer.periodic(positionInterval, (_) => sendPosition());
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      now = DateTime.now().toUtc();
      notifyListeners();
    });
    unawaited(sendPosition());
  }

  @override
  void dispose() {
    _disposed = true;
    _poll?.cancel();
    _gps?.cancel();
    _tick?.cancel();
    _wsSub?.cancel();
    _ws?.connected.removeListener(_onWsStatus);
    unawaited(_ws?.dispose());
    unawaited(_tts?.stop());
    super.dispose();
  }

  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }

  // ------------------------------------------------------------------ cache
  void _loadCache() {
    final c = cache.getJson(_cacheKey, (j) => asMap(j));
    if (c == null) return;
    final m = c.value;
    if (m['appointment'] is Map) {
      appointment = Appointment.fromJson(asMap(m['appointment']));
    }
    if (m['station'] is Map) station = Station.fromJson(asMap(m['station']));
    if (m['latest'] is Map) latest = WeighingEvent.fromJson(asMap(m['latest']));
    lastUpdated = c.storedAt;
    fromCache = true;
    _spokenDecisionId = latest?.decision?.id; // never re-announce a cached decision
  }

  Future<void> _saveCache() => cache.putJson(_cacheKey, {
        'appointment': appointment?.raw,
        'station': station?.raw,
        'latest': latest?.raw,
      });

  // ------------------------------------------------------------------ refresh
  Future<void> refreshAll({bool triggeredByEvent = false}) async {
    if (_refreshing || _disposed) return;
    _refreshing = true;
    var networkFailed = false;
    error = null;

    try {
      final list = asMapList(await api.get('/queue/appointments/mine'));
      appointment = _pickAppointment(list.map(Appointment.fromJson));
    } on NetworkException {
      networkFailed = true;
    } on ApiException catch (e) {
      error = e.detail;
    }

    try {
      final list = asMapList(await api.get('/weighing/events',
          query: {'vehicle_id': vehicle.id, 'limit': '1'}));
      latest = list.isEmpty ? null : WeighingEvent.fromJson(list.first);
    } on NetworkException {
      networkFailed = true;
    } on ApiException catch (e) {
      error = e.detail;
    }

    final stationId = appointment?.stationId ?? latest?.stationId;
    if (stationId != null && stationId.isNotEmpty) {
      try {
        station = Station.fromJson(asMap(await api.get('/stations/$stationId')));
      } on NetworkException {
        networkFailed = true;
      } on ApiException catch (e) {
        error = e.detail;
      }
    } else {
      station = null;
    }

    offline = networkFailed;
    if (!networkFailed) {
      lastUpdated = DateTime.now();
      fromCache = false;
      await _saveCache();
      if (queuedPositions > 0) {
        await _posQueue.flush(api);
        queuedPositions = _posQueue.length;
      }
    }
    _refreshing = false;
    _maybeSpeak(force: triggeredByEvent);
    _safeNotify();
  }

  Appointment? _pickAppointment(Iterable<Appointment> all) {
    final mine = all
        .where((a) => a.vehicleId == vehicle.id && a.isActive)
        .toList()
      ..sort((a, b) => a.slotStart.compareTo(b.slotStart));
    if (mine.isEmpty) return null;
    final cutoff = DateTime.now().toUtc().subtract(const Duration(hours: 2));
    for (final a in mine) {
      if (a.slotEnd.isAfter(cutoff)) return a;
    }
    return mine.last;
  }

  // ------------------------------------------------------------------ websocket
  void _onWsStatus() {
    wsConnected = _ws?.connected.value ?? false;
    _safeNotify();
  }

  void _onWsEvent(WsEvent ev) {
    switch (ev.type) {
      case 'clearance.decided':
        // Payload carries `plate` (not vehicle_id) and no qr_token, so we
        // re-fetch the full event for this vehicle.
        final plate = asString(ev.payload['plate']);
        if (normalisePlate(plate) == normalisePlate(vehicle.plate)) {
          unawaited(refreshAll(triggeredByEvent: true));
        }
        break;
      case 'queue.updated':
        final sid = ev.stationId ?? asString(ev.payload['station_id']);
        if (sid != null && sid == station?.id) {
          final q = asInt(ev.payload['queue_len']);
          final w = asInt(ev.payload['avg_wait_s']);
          if (q != null && w != null && station != null) {
            station = station!.withQueue(queueLen: q, avgWaitS: w);
            lastUpdated = DateTime.now();
            unawaited(_saveCache());
            _safeNotify();
          } else {
            unawaited(refreshAll());
          }
        }
        break;
      default:
        break;
    }
  }

  // ------------------------------------------------------------------ speech
  void _maybeSpeak({bool force = false}) {
    final d = decision;
    if (d == null || d.id == _spokenDecisionId) return;
    final at = d.decidedAt;
    final fresh = at != null &&
        DateTime.now().toUtc().difference(at) < speakIfYoungerThan;
    if (!force && !fresh) {
      _spokenDecisionId = d.id;
      return;
    }
    _spokenDecisionId = d.id;
    unawaited(speakCurrent());
  }

  List<String> get _speechLanguages {
    switch (settings.ttsMode) {
      case 'en':
        return const ['en'];
      case 'sw':
        return const ['sw'];
      default:
        final first = settings.language;
        return [first, first == 'en' ? 'sw' : 'en'];
    }
  }

  /// Reads "<decision>. <instruction>" aloud in the configured language(s).
  Future<void> speakCurrent() async {
    final d = decision;
    if (d == null) return;
    final ins = instruction;
    try {
      final tts = _tts ??= FlutterTts();
      await tts.awaitSpeakCompletion(true);
      await tts.setSpeechRate(0.45);
      for (final lang in _speechLanguages) {
        final l = L10n(lang);
        try {
          await tts.setLanguage(l.ttsLocale);
        } catch (_) {
          // engine may lack sw-KE; it will fall back to its default voice
        }
        await tts.speak('${l.decision(d.decision)}. ${l.t(ins.key, ins.params)}');
      }
    } catch (_) {
      // No TTS engine on this device: the visual panel is still authoritative.
    }
  }

  // ------------------------------------------------------------------ GPS
  Future<void> sendPosition() async {
    if (_disposed) return;
    try {
      final perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied ||
          perm == LocationPermission.deniedForever) {
        gpsStatus = 'denied';
        _safeNotify();
        return;
      }
      final pos = await Geolocator.getCurrentPosition()
          .timeout(const Duration(seconds: 25));
      final sample = PositionSample(
        vehicleId: vehicle.id,
        lat: pos.latitude,
        lon: pos.longitude,
        at: DateTime.now().toUtc(),
      );
      try {
        if (_posQueue.length > 0) await _posQueue.flush(api);
        await api.post('/fleet/vehicles/${vehicle.id}/position',
            body: {'lat': sample.lat, 'lon': sample.lon});
        gpsStatus = 'sent';
      } on NetworkException {
        await _posQueue.enqueue(sample);
        gpsStatus = 'queued';
      } on ApiException catch (e) {
        gpsStatus = 'error';
        error = e.detail;
      }
    } catch (_) {
      gpsStatus = 'error';
    }
    queuedPositions = _posQueue.length;
    _safeNotify();
  }
}
