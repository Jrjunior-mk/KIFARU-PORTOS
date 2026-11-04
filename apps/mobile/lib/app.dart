import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/api_client.dart';
import 'core/cache.dart';
import 'screens/home_gate.dart';
import 'screens/login_screen.dart';
import 'state/app_settings.dart';
import 'state/auth_state.dart';

class KifaruApp extends StatelessWidget {
  const KifaruApp({
    super.key,
    required this.settings,
    required this.api,
    required this.auth,
    required this.cache,
  });

  final AppSettings settings;
  final ApiClient api;
  final AuthState auth;
  final LocalCache cache;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        Provider<LocalCache>.value(value: cache),
        ChangeNotifierProvider<AppSettings>.value(value: settings),
        ChangeNotifierProvider<AuthState>.value(value: auth),
      ],
      child: Consumer<AppSettings>(
        builder: (context, s, _) => MaterialApp(
          title: 'KIFARU PORTOS',
          debugShowCheckedModeBanner: false,
          theme: ThemeData(
            useMaterial3: true,
            colorSchemeSeed: const Color(0xFF0F766E),
            brightness: Brightness.light,
          ),
          darkTheme: ThemeData(
            useMaterial3: true,
            colorSchemeSeed: const Color(0xFF0F766E),
            brightness: Brightness.dark,
          ),
          // UI strings are map-based (lib/l10n); `s.language` is read there.
          // Material's own delegates stay English, so no `locale:` override.
          home: const _RootGate(),
        ),
      ),
    );
  }
}

class _RootGate extends StatelessWidget {
  const _RootGate();

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthState>();
    switch (auth.status) {
      case AuthStatus.loading:
        return const Scaffold(body: Center(child: CircularProgressIndicator()));
      case AuthStatus.signedOut:
        return const LoginScreen();
      case AuthStatus.signedIn:
        return const HomeGate();
    }
  }
}
