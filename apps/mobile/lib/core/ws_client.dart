import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'json_utils.dart';

/// One event from `/ws/events`: `{type, occurred_at, station_id, org_id, payload}`.
class WsEvent {
  WsEvent({
    required this.type,
    required this.occurredAt,
    required this.stationId,
    required this.orgId,
    required this.payload,
    required this.raw,
  });

  factory WsEvent.fromJson(Map<String, dynamic> j) => WsEvent(
        type: asString(j['type']) ?? '',
        occurredAt: parseUtc(j['occurred_at']),
        stationId: asString(j['station_id']),
        orgId: asString(j['org_id']),
        payload: asMap(j['payload']),
        raw: j,
      );

  final String type;
  final DateTime? occurredAt;
  final String? stationId;
  final String? orgId;
  final Map<String, dynamic> payload;
  final Map<String, dynamic> raw;
}

/// Reconnecting WebSocket with exponential back-off (1 s -> 30 s, jittered).
///
/// [urlBuilder] is invoked on every (re)connect so a refreshed JWT is used.
/// Server `ping` frames are swallowed; the `hello` frame's `recent` list is
/// replayed through [events] so a late joiner sees the last few events.
class WsClient {
  WsClient({required this.urlBuilder});

  final Future<Uri?> Function() urlBuilder;
  final _controller = StreamController<WsEvent>.broadcast();
  final ValueNotifier<bool> connected = ValueNotifier<bool>(false);

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  Timer? _retry;
  int _attempt = 0;
  bool _closed = false;

  Stream<WsEvent> get events => _controller.stream;

  Future<void> connect() async {
    if (_closed) return;
    _retry?.cancel();
    final uri = await urlBuilder();
    if (uri == null) {
      _scheduleReconnect();
      return;
    }
    try {
      final ch = WebSocketChannel.connect(uri);
      await ch.ready;
      _channel = ch;
      _attempt = 0;
      connected.value = true;
      _sub = ch.stream.listen(
        _onData,
        onError: (Object _) => _onClosed(),
        onDone: _onClosed,
        cancelOnError: true,
      );
    } catch (_) {
      _onClosed();
    }
  }

  void _onData(dynamic data) {
    if (data is! String) return;
    Object? decoded;
    try {
      decoded = jsonDecode(data);
    } catch (_) {
      return;
    }
    if (decoded is! Map) return;
    final j = Map<String, dynamic>.from(decoded);
    final type = asString(j['type']);
    if (type == 'ping') return;
    if (type == 'hello') {
      for (final r in asMapList(j['recent'])) {
        _controller.add(WsEvent.fromJson(r));
      }
      return;
    }
    _controller.add(WsEvent.fromJson(j));
  }

  void _onClosed() {
    if (_closed) return;
    connected.value = false;
    _sub?.cancel();
    _sub = null;
    _channel = null;
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (_closed) return;
    _retry?.cancel();
    final base = min(30000, 1000 * pow(2, _attempt).toInt());
    final jitter = Random().nextInt(500);
    _attempt = min(_attempt + 1, 6);
    _retry = Timer(Duration(milliseconds: base + jitter), connect);
  }

  /// Force a reconnect (e.g. after the access token changed).
  Future<void> reconnect() async {
    await _sub?.cancel();
    _sub = null;
    await _channel?.sink.close();
    _channel = null;
    connected.value = false;
    _attempt = 0;
    await connect();
  }

  Future<void> dispose() async {
    _closed = true;
    _retry?.cancel();
    await _sub?.cancel();
    await _channel?.sink.close();
    await _controller.close();
    connected.dispose();
  }
}
