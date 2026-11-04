import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/strings.dart';
import '../state/app_settings.dart';
import '../state/auth_state.dart';

/// API base URL, public verify URL, language (en/sw), low-bandwidth mode and
/// spoken-announcement language. Works both as a pushed page and as a tab.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, this.embedded = false});
  final bool embedded;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _baseUrl;
  late final TextEditingController _publicUrl;

  @override
  void initState() {
    super.initState();
    final s = context.read<AppSettings>();
    _baseUrl = TextEditingController(text: s.baseUrl);
    _publicUrl = TextEditingController(text: s.publicBaseUrl);
  }

  @override
  void dispose() {
    _baseUrl.dispose();
    _publicUrl.dispose();
    super.dispose();
  }

  Future<void> _saveUrls() async {
    final s = context.read<AppSettings>();
    final auth = context.read<AuthState>();
    final l = s.l10n;
    final changedApi = _baseUrl.text.trim() != s.baseUrl;
    final uri = Uri.tryParse(_baseUrl.text.trim());
    if (uri == null || !(uri.scheme == 'http' || uri.scheme == 'https') || uri.host.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.t('api_url_hint'))));
      return;
    }
    await s.setBaseUrl(_baseUrl.text);
    await s.setPublicBaseUrl(_publicUrl.text);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l.t('saved'))));
    if (changedApi && auth.status == AuthStatus.signedIn) {
      await auth.logout();
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppSettings>();
    final l = s.l10n;
    final auth = context.watch<AuthState>();
    return Scaffold(
      appBar: AppBar(
        title: Text(l.t('settings')),
        automaticallyImplyLeading: !widget.embedded,
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _baseUrl,
            keyboardType: TextInputType.url,
            decoration: InputDecoration(
                labelText: l.t('api_url'), helperText: l.t('api_url_hint')),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _publicUrl,
            keyboardType: TextInputType.url,
            decoration: InputDecoration(labelText: l.t('public_base_url')),
          ),
          const SizedBox(height: 8),
          Text(l.t('relogin_hint'), style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 8),
          FilledButton(onPressed: _saveUrls, child: Text(l.t('save'))),
          const Divider(height: 32),
          Text(l.t('language'), style: Theme.of(context).textTheme.titleMedium),
          ...L10n.supported.map((code) => RadioListTile<String>(
                value: code,
                groupValue: s.language,
                title: Text(L10n.languageName(code)),
                onChanged: (v) => s.setLanguage(v ?? 'en'),
              )),
          const Divider(height: 32),
          SwitchListTile(
            value: s.lowBandwidth,
            title: Text(l.t('low_bandwidth')),
            subtitle: Text(l.t('low_bandwidth_hint')),
            onChanged: s.setLowBandwidth,
          ),
          const Divider(height: 32),
          Text(l.t('tts_mode'), style: Theme.of(context).textTheme.titleMedium),
          for (final m in const ['both', 'sw', 'en'])
            RadioListTile<String>(
              value: m,
              groupValue: s.ttsMode,
              title: Text(l.t('tts_$m')),
              onChanged: (v) => s.setTtsMode(v ?? 'both'),
            ),
          const Divider(height: 32),
          if (auth.status == AuthStatus.signedIn)
            OutlinedButton.icon(
              onPressed: auth.logout,
              icon: const Icon(Icons.logout),
              label: Text('${l.t('sign_out')}  (${auth.me?.email ?? ''})'),
            ),
          const SizedBox(height: 16),
          Text(l.t('about_not_compiled'), style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}
