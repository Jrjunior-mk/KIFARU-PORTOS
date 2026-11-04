import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/api_client.dart';
import '../core/api_exceptions.dart';
import '../core/cache.dart';
import '../core/json_utils.dart';
import '../models/me.dart';
import '../models/token.dart';

enum AuthStatus { loading, signedOut, signedIn }

/// Login / refresh / logout and the current principal (`/auth/me`).
///
/// Tokens live in the platform keystore (flutter_secure_storage); the `Me`
/// profile is cached in shared_preferences so the app can open offline.
class AuthState extends ChangeNotifier {
  AuthState({
    required this.api,
    required FlutterSecureStorage storage,
    required this.cache,
  }) : _storage = storage {
    api.onRefresh = _refresh;
    api.onAuthLost = _onAuthLost;
  }

  final ApiClient api;
  final FlutterSecureStorage _storage;
  final LocalCache cache;

  static const _kAccess = 'kifaru.access_token';
  static const _kRefresh = 'kifaru.refresh_token';
  static const _kMe = 'auth.me';

  AuthStatus status = AuthStatus.loading;
  Me? me;
  String? error;
  bool busy = false;
  bool mfaRequired = false;
  String? _refreshToken;

  Future<void> init() async {
    final access = await _storage.read(key: _kAccess);
    _refreshToken = await _storage.read(key: _kRefresh);
    if (access == null && _refreshToken == null) {
      status = AuthStatus.signedOut;
      notifyListeners();
      return;
    }
    api.accessToken = access;
    try {
      await _loadMe();
      status = AuthStatus.signedIn;
    } on UnauthorizedException {
      await _clear();
      status = AuthStatus.signedOut;
    } on NetworkException {
      final cached = cache.getJson(_kMe, (j) => Me.fromJson(asMap(j)));
      if (cached != null) {
        me = cached.value;
        status = AuthStatus.signedIn;
      } else {
        status = AuthStatus.signedOut;
      }
    } on ApiException catch (e) {
      error = e.detail;
      status = AuthStatus.signedOut;
    }
    notifyListeners();
  }

  Future<bool> login(String email, String password, {String? totpCode}) async {
    busy = true;
    error = null;
    notifyListeners();
    try {
      final j = await api.post('/auth/login', auth: false, body: {
        'email': email.trim(),
        'password': password,
        if (totpCode != null && totpCode.trim().isNotEmpty)
          'totp_code': totpCode.trim(),
      });
      final token = Token.fromJson(asMap(j));
      mfaRequired = token.mfaRequired;
      await _store(token);
      await _loadMe();
      status = AuthStatus.signedIn;
      return true;
    } on ApiException catch (e) {
      error = e.detail;
      return false;
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    final rt = _refreshToken;
    if (rt != null) {
      try {
        await api.post('/auth/logout', body: {'refresh_token': rt});
      } on ApiException {
        // best effort; the refresh session expires server-side anyway
      }
    }
    await _clear();
    status = AuthStatus.signedOut;
    notifyListeners();
  }

  Future<void> _loadMe() async {
    final j = await api.get('/auth/me');
    me = Me.fromJson(asMap(j));
    await cache.putJson(_kMe, me!.raw);
  }

  Future<void> _store(Token t) async {
    api.accessToken = t.accessToken;
    _refreshToken = t.refreshToken;
    await _storage.write(key: _kAccess, value: t.accessToken);
    await _storage.write(key: _kRefresh, value: t.refreshToken);
  }

  Future<void> _clear() async {
    api.accessToken = null;
    _refreshToken = null;
    me = null;
    await _storage.delete(key: _kAccess);
    await _storage.delete(key: _kRefresh);
    await cache.remove(_kMe);
  }

  /// Called by [ApiClient] on a 401. Rotating refresh: the old token is
  /// revoked server-side and a new pair is returned.
  Future<bool> _refresh() async {
    final rt = _refreshToken;
    if (rt == null) return false;
    try {
      final j = await api.post('/auth/refresh',
          auth: false, body: {'refresh_token': rt});
      await _store(Token.fromJson(asMap(j)));
      return true;
    } on ApiException {
      return false;
    }
  }

  Future<void> _onAuthLost() async {
    if (status == AuthStatus.signedOut) return;
    await _clear();
    status = AuthStatus.signedOut;
    error = 'Session expired. Please sign in again.';
    notifyListeners();
  }
}
