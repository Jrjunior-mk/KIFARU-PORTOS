import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/api_client.dart';
import '../core/api_exceptions.dart';
import '../core/cache.dart';
import '../core/json_utils.dart';
import '../core/ws_client.dart';
import '../models/notification.dart';
import '../models/shipment.dart';
import 'app_settings.dart';

/// Shipments (cargo passports) and the notification inbox for a cargo owner.
///
/// Reads `GET /shipments`, `GET /notifications`; writes `POST /shipments` and
/// `POST /notifications/{id}/read`. Both lists are cached for offline viewing.
class CargoState extends ChangeNotifier {
  CargoState({required this.api, required this.cache, required this.settings});

  final ApiClient api;
  final LocalCache cache;
  final AppSettings settings;

  static const _kShipments = 'cargo.shipments';
  static const _kInbox = 'cargo.inbox';

  List<ShipmentPassport> shipments = [];
  List<AppNotification> notifications = [];
  DateTime? shipmentsUpdated;
  DateTime? inboxUpdated;
  bool loadingShipments = false;
  bool loadingInbox = false;
  bool offline = false;
  String? error;
  bool wsConnected = false;

  WsClient? _ws;
  StreamSubscription<WsEvent>? _wsSub;
  Timer? _poll;
  bool _disposed = false;

  int get unreadCount => notifications.where((n) => !n.isRead).length;

  Future<void> start() async {
    _loadCache();
    notifyListeners();
    await Future.wait([loadShipments(), loadInbox()]);
    _ws = WsClient(urlBuilder: () async {
      final t = api.accessToken;
      if (t == null) return null;
      return api.wsUri(t, types: const [
        'cargo.status_changed',
        'cargo.verified',
        'shipment.delivered',
        'notification',
      ]);
    });
    _ws!.connected.addListener(() {
      wsConnected = _ws?.connected.value ?? false;
      _safeNotify();
    });
    _wsSub = _ws!.events.listen(_onWsEvent);
    unawaited(_ws!.connect());
    _restartPolling();
    settings.addListener(_restartPolling);
  }

  void _restartPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(settings.cargoPollInterval, (_) {
      unawaited(loadShipments());
      unawaited(loadInbox());
    });
  }

  @override
  void dispose() {
    _disposed = true;
    settings.removeListener(_restartPolling);
    _poll?.cancel();
    _wsSub?.cancel();
    unawaited(_ws?.dispose());
    super.dispose();
  }

  void _safeNotify() {
    if (!_disposed) notifyListeners();
  }

  void _loadCache() {
    final s = cache.getJson(_kShipments, (j) => asMapList(j));
    if (s != null) {
      shipments = s.value.map(ShipmentPassport.fromJson).toList();
      shipmentsUpdated = s.storedAt;
    }
    final n = cache.getJson(_kInbox, (j) => asMapList(j));
    if (n != null) {
      notifications = n.value.map(AppNotification.fromJson).toList();
      inboxUpdated = n.storedAt;
    }
  }

  void _onWsEvent(WsEvent ev) {
    switch (ev.type) {
      case 'cargo.status_changed':
      case 'cargo.verified':
      case 'shipment.delivered':
        unawaited(loadShipments());
        break;
      case 'notification':
        unawaited(loadInbox());
        break;
      default:
        break;
    }
  }

  Future<void> loadShipments() async {
    if (_disposed) return;
    loadingShipments = true;
    _safeNotify();
    try {
      final list = asMapList(await api.get('/shipments'));
      shipments = list.map(ShipmentPassport.fromJson).toList();
      shipmentsUpdated = DateTime.now();
      offline = false;
      error = null;
      await cache.putJson(_kShipments, list);
    } on NetworkException {
      offline = true;
    } on ApiException catch (e) {
      error = e.detail;
    } finally {
      loadingShipments = false;
      _safeNotify();
    }
  }

  Future<void> loadInbox() async {
    if (_disposed) return;
    loadingInbox = true;
    _safeNotify();
    try {
      final list = asMapList(await api.get('/notifications'));
      notifications = list.map(AppNotification.fromJson).toList();
      inboxUpdated = DateTime.now();
      offline = false;
      await cache.putJson(_kInbox, list);
    } on NetworkException {
      offline = true;
    } on ApiException catch (e) {
      error = e.detail;
    } finally {
      loadingInbox = false;
      _safeNotify();
    }
  }

  /// `GET /shipments/{id}` (id or reference). Throws [ApiException].
  Future<ShipmentPassport> fetchPassport(String idOrReference) async {
    final j = asMap(await api.get('/shipments/$idOrReference'));
    final p = ShipmentPassport.fromJson(j);
    final i = shipments.indexWhere((s) => s.id == p.id);
    if (i >= 0) {
      shipments[i] = p;
    } else {
      shipments.insert(0, p);
    }
    await cache.putJson(_kShipments, shipments.map((s) => s.raw).toList());
    _safeNotify();
    return p;
  }

  /// `POST /shipments`. Throws [ApiException] (422 -> [ValidationException]).
  Future<ShipmentPassport> register(Map<String, dynamic> body) async {
    final j = asMap(await api.post('/shipments', body: body));
    final p = ShipmentPassport.fromJson(j);
    shipments.insert(0, p);
    await cache.putJson(_kShipments, shipments.map((s) => s.raw).toList());
    _safeNotify();
    return p;
  }

  Future<void> markRead(AppNotification n) async {
    final i = notifications.indexWhere((x) => x.id == n.id);
    if (i >= 0) {
      notifications[i] = n.markedRead();
      _safeNotify();
    }
    try {
      await api.post('/notifications/${n.id}/read');
    } on ApiException {
      // keep the optimistic local state; next inbox poll reconciles
    }
  }
}
