import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/api_exceptions.dart';
import '../core/format.dart';
import '../core/json_utils.dart';
import '../l10n/strings.dart';
import '../models/ticket_verification.dart';
import '../state/app_settings.dart';
import '../widgets/error_banner.dart';
import '../widgets/source_badge.dart';

/// Public ticket verification: `GET /tickets/verify/{qr_token}` (no auth).
/// The token is the last path segment of the QR URL, so a pasted URL works too.
class TicketVerifyScreen extends StatefulWidget {
  const TicketVerifyScreen({super.key, this.initialToken});
  final String? initialToken;

  @override
  State<TicketVerifyScreen> createState() => _TicketVerifyScreenState();
}

class _TicketVerifyScreenState extends State<TicketVerifyScreen> {
  late final TextEditingController _token =
      TextEditingController(text: widget.initialToken ?? '');
  TicketVerification? _result;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    if ((widget.initialToken ?? '').isNotEmpty) _verify();
  }

  @override
  void dispose() {
    _token.dispose();
    super.dispose();
  }

  String _extractToken(String input) {
    final s = input.trim();
    final uri = Uri.tryParse(s);
    if (uri != null && uri.pathSegments.isNotEmpty && s.contains('/')) {
      return uri.pathSegments.last;
    }
    return s;
  }

  Future<void> _verify() async {
    final tok = _extractToken(_token.text);
    if (tok.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
    });
    try {
      final j = asMap(await context
          .read<ApiClient>()
          .get('/tickets/verify/${Uri.encodeComponent(tok)}', auth: false));
      if (mounted) setState(() => _result = TicketVerification.fromJson(j));
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.detail);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final r = _result;
    return Scaffold(
      appBar: AppBar(title: Text(l.t('verify_ticket'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_error != null) ErrorBanner(_error!, onRetry: _verify),
          TextField(
            controller: _token,
            decoration: InputDecoration(
              labelText: l.t('qr_token'),
              suffixIcon: IconButton(
                  icon: const Icon(Icons.search), onPressed: _busy ? null : _verify),
            ),
            onSubmitted: (_) => _verify(),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _busy ? null : _verify,
            child: _busy
                ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                : Text(l.t('verify')),
          ),
          const SizedBox(height: 24),
          if (r != null) _ResultCard(r: r, l: l),
        ],
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.r, required this.l});
  final TicketVerification r;
  final L10n l;

  @override
  Widget build(BuildContext context) {
    final ok = r.valid;
    final color = ok ? const Color(0xFF1B5E20) : const Color(0xFFB71C1C);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(ok ? Icons.verified : Icons.gpp_bad, color: color, size: 36),
                const SizedBox(width: 12),
                Text(ok ? l.t('ticket_valid') : l.t('ticket_invalid'),
                    style: TextStyle(color: color, fontSize: 28, fontWeight: FontWeight.bold)),
                const Spacer(),
                if (r.source != null) SourceBadge(r.source!),
              ],
            ),
            const SizedBox(height: 12),
            if (!ok && r.ticketType == null) Text(l.t('ticket_not_found')),
            if (r.ticketType != null) _row('Type', r.ticketType!),
            if (r.legalStatus != null) _row(l.t('legal_status'), r.legalStatus!),
            if (r.plate != null) _row('Plate', r.plate!),
            if (r.gvmKg != null) _row('GVM', '${fmtKg(r.gvmKg!)} kg'),
            if (r.decision != null) _row('Decision', r.decision!),
            if (r.station != null) _row('Station', r.station!),
            if (r.occurredAt != null) _row('Time', fmtLocal(r.occurredAt)),
            if (r.evidenceHash != null)
              _row(l.t('evidence_hash'), r.evidenceHash!, mono: true),
          ],
        ),
      ),
    );
  }

  Widget _row(String k, String v, {bool mono = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(width: 110, child: Text(k, style: const TextStyle(fontWeight: FontWeight.w600))),
            Expanded(
                child: Text(v,
                    style: mono ? const TextStyle(fontFamily: 'monospace', fontSize: 12) : null)),
          ],
        ),
      );
}
