import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_settings.dart';
import '../state/auth_state.dart';
import 'settings_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _totp = TextEditingController();
  bool _showTotp = false;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _totp.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_form.currentState?.validate() ?? false)) return;
    final auth = context.read<AuthState>();
    await auth.login(_email.text, _password.text,
        totpCode: _showTotp ? _totp.text : null);
    if (!mounted) return;
    if (auth.status != AuthStatus.signedIn && auth.mfaRequired) {
      setState(() => _showTotp = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<AppSettings>();
    final l = settings.l10n;
    final auth = context.watch<AuthState>();
    return Scaffold(
      appBar: AppBar(
        title: Text(l.t('app_title')),
        actions: [
          IconButton(
            tooltip: l.t('settings'),
            icon: const Icon(Icons.settings),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const SettingsScreen()),
            ),
          ),
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Form(
              key: _form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(l.t('login_title'),
                      style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 8),
                  Text(settings.baseUrl,
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 24),
                  TextFormField(
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.username],
                    decoration: InputDecoration(labelText: l.t('email')),
                    validator: (v) =>
                        (v == null || !v.contains('@')) ? l.t('required') : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _password,
                    obscureText: true,
                    autofillHints: const [AutofillHints.password],
                    decoration: InputDecoration(labelText: l.t('password')),
                    validator: (v) =>
                        (v == null || v.isEmpty) ? l.t('required') : null,
                    onFieldSubmitted: (_) => _submit(),
                  ),
                  const SizedBox(height: 12),
                  if (_showTotp)
                    TextFormField(
                      controller: _totp,
                      keyboardType: TextInputType.number,
                      maxLength: 8,
                      decoration: InputDecoration(labelText: l.t('totp_code')),
                    )
                  else
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton(
                        onPressed: () => setState(() => _showTotp = true),
                        child: Text(l.t('totp_code')),
                      ),
                    ),
                  const SizedBox(height: 16),
                  if (auth.error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(auth.error!,
                          style: TextStyle(
                              color: Theme.of(context).colorScheme.error)),
                    ),
                  FilledButton(
                    onPressed: auth.busy ? null : _submit,
                    child: auth.busy
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : Text(l.t('sign_in')),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
