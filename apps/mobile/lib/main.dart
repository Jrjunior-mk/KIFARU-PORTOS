import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app.dart';
import 'core/api_client.dart';
import 'core/cache.dart';
import 'state/app_settings.dart';
import 'state/auth_state.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await SharedPreferences.getInstance();
  final settings = AppSettings(prefs);
  final cache = LocalCache(prefs);
  final api = ApiClient(baseUrl: () => settings.baseUrl);
  final auth = AuthState(
    api: api,
    storage: const FlutterSecureStorage(),
    cache: cache,
  );
  unawaited(auth.init());
  runApp(KifaruApp(settings: settings, api: api, auth: auth, cache: cache));
}
