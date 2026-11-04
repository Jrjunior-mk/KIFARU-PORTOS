import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../l10n/strings.dart';

/// User-editable configuration, persisted in shared_preferences.
class AppSettings extends ChangeNotifier {
  AppSettings(this._prefs)
      : _baseUrl = _prefs.getString(_kBaseUrl) ?? defaultBaseUrl,
        _publicBaseUrl = _prefs.getString(_kPublicBaseUrl) ?? defaultPublicBaseUrl,
        _language = _prefs.getString(_kLanguage) ?? 'en',
        _lowBandwidth = _prefs.getBool(_kLowBandwidth) ?? false,
        _ttsMode = _prefs.getString(_kTtsMode) ?? 'both';

  final SharedPreferences _prefs;

  static const _kBaseUrl = 'kifaru.settings.base_url';
  static const _kPublicBaseUrl = 'kifaru.settings.public_base_url';
  static const _kLanguage = 'kifaru.settings.language';
  static const _kLowBandwidth = 'kifaru.settings.low_bandwidth';
  static const _kTtsMode = 'kifaru.settings.tts_mode';

  /// Android emulator loopback to a dev API on the host machine.
  static const defaultBaseUrl = 'http://10.0.2.2:8000';

  /// Matches the API's `public_base_url` default (the web app that serves
  /// `/verify/{qr_token}`). There is no endpoint exposing it, so it is a setting.
  static const defaultPublicBaseUrl = 'http://localhost:5173';

  String _baseUrl;
  String _publicBaseUrl;
  String _language;
  bool _lowBandwidth;
  String _ttsMode;

  String get baseUrl => _baseUrl;
  String get publicBaseUrl => _publicBaseUrl;
  String get language => _language;
  bool get lowBandwidth => _lowBandwidth;

  /// `both | en | sw`
  String get ttsMode => _ttsMode;

  L10n get l10n => L10n(_language);

  /// Polling cadence for the driver screen (the WebSocket is primary; this is
  /// the fallback).
  Duration get driverPollInterval =>
      _lowBandwidth ? const Duration(seconds: 90) : const Duration(seconds: 30);

  Duration get cargoPollInterval =>
      _lowBandwidth ? const Duration(minutes: 5) : const Duration(seconds: 60);

  String verifyUrl(String qrToken) {
    var b = _publicBaseUrl.trim();
    while (b.endsWith('/')) {
      b = b.substring(0, b.length - 1);
    }
    return '$b/verify/$qrToken';
  }

  Future<void> setBaseUrl(String v) async {
    _baseUrl = v.trim();
    await _prefs.setString(_kBaseUrl, _baseUrl);
    notifyListeners();
  }

  Future<void> setPublicBaseUrl(String v) async {
    _publicBaseUrl = v.trim();
    await _prefs.setString(_kPublicBaseUrl, _publicBaseUrl);
    notifyListeners();
  }

  Future<void> setLanguage(String v) async {
    _language = L10n.supported.contains(v) ? v : 'en';
    await _prefs.setString(_kLanguage, _language);
    notifyListeners();
  }

  Future<void> setLowBandwidth(bool v) async {
    _lowBandwidth = v;
    await _prefs.setBool(_kLowBandwidth, v);
    notifyListeners();
  }

  Future<void> setTtsMode(String v) async {
    _ttsMode = const ['both', 'en', 'sw'].contains(v) ? v : 'both';
    await _prefs.setString(_kTtsMode, _ttsMode);
    notifyListeners();
  }
}
