import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'api_exceptions.dart';

/// Thin JSON client for the KIFARU PORTOS API.
///
/// * Base URL is read lazily from [_baseUrl] so Settings changes apply at once.
/// * Adds `Authorization: Bearer` when [accessToken] is set.
/// * On 401 it calls [onRefresh] once (de-duplicated across concurrent
///   requests) and retries; if refresh fails it calls [onAuthLost].
/// * Non-2xx responses throw a typed [ApiException] carrying `detail`.
class ApiClient {
  ApiClient({
    required String Function() baseUrl,
    http.Client? client,
    this.timeout = const Duration(seconds: 20),
  })  : _baseUrl = baseUrl,
        _http = client ?? http.Client();

  static const apiPrefix = '/api/v1';

  final String Function() _baseUrl;
  final http.Client _http;
  final Duration timeout;

  String? accessToken;
  Future<bool> Function()? onRefresh;
  Future<void> Function()? onAuthLost;
  Future<bool>? _refreshing;

  String get baseUrl {
    var b = _baseUrl().trim();
    while (b.endsWith('/')) {
      b = b.substring(0, b.length - 1);
    }
    return b;
  }

  Uri uri(String path, [Map<String, String?>? query]) {
    final q = <String, String>{};
    query?.forEach((k, v) {
      if (v != null && v.isNotEmpty) q[k] = v;
    });
    final u = Uri.parse('$baseUrl$apiPrefix$path');
    return q.isEmpty ? u : u.replace(queryParameters: q);
  }

  /// `ws(s)://host/ws/events?token=...&types=a,b` derived from the base URL.
  Uri wsUri(String token, {List<String>? types, String? station}) {
    final base = Uri.parse(baseUrl);
    final q = <String, String>{
      'token': token,
      if (types != null && types.isNotEmpty) 'types': types.join(','),
      if (station != null && station.isNotEmpty) 'station': station,
    };
    return base.replace(
      scheme: base.scheme == 'https' ? 'wss' : 'ws',
      path: '/ws/events',
      queryParameters: q,
    );
  }

  Future<dynamic> get(String path,
          {Map<String, String?>? query, bool auth = true}) =>
      _send('GET', path, query: query, auth: auth);

  Future<dynamic> post(String path,
          {Object? body, Map<String, String?>? query, bool auth = true}) =>
      _send('POST', path, body: body, query: query, auth: auth);

  Future<dynamic> _send(
    String method,
    String path, {
    Object? body,
    Map<String, String?>? query,
    bool auth = true,
    bool retried = false,
  }) async {
    final req = http.Request(method, uri(path, query));
    req.headers['Accept'] = 'application/json';
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    if (auth && accessToken != null) {
      req.headers['Authorization'] = 'Bearer $accessToken';
    }

    http.Response res;
    try {
      final streamed = await _http.send(req).timeout(timeout);
      res = await http.Response.fromStream(streamed).timeout(timeout);
    } on SocketException catch (e) {
      throw NetworkException('Cannot reach server (${e.message})');
    } on HandshakeException catch (e) {
      throw NetworkException('TLS handshake failed (${e.message})');
    } on TimeoutException {
      throw NetworkException('Request timed out');
    } on http.ClientException catch (e) {
      throw NetworkException(e.message);
    }

    if (res.statusCode == 401 && auth && !retried && onRefresh != null) {
      final ok = await _refreshOnce();
      if (ok) {
        return _send(method, path,
            body: body, query: query, auth: auth, retried: true);
      }
      await onAuthLost?.call();
    }
    return _decode(res);
  }

  Future<bool> _refreshOnce() {
    final inflight = _refreshing;
    if (inflight != null) return inflight;
    final f = onRefresh!().catchError((Object _) => false);
    _refreshing = f;
    f.whenComplete(() => _refreshing = null);
    return f;
  }

  dynamic _decode(http.Response res) {
    Object? json;
    if (res.bodyBytes.isNotEmpty) {
      final text = utf8.decode(res.bodyBytes, allowMalformed: true);
      try {
        json = jsonDecode(text);
      } catch (_) {
        json = text;
      }
    }
    if (res.statusCode >= 200 && res.statusCode < 300) return json;
    throw ApiException.fromResponse(res.statusCode, json);
  }

  void close() => _http.close();
}
