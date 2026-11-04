import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../core/api_exceptions.dart';
import '../core/format.dart';
import '../l10n/strings.dart';
import '../models/shipment.dart';
import '../state/app_settings.dart';
import '../state/cargo_state.dart';
import '../widgets/error_banner.dart';
import '../widgets/source_badge.dart';
import 'ticket_verify_screen.dart';

/// Digital Cargo Passport detail: stage timeline, outstanding items, weighings
/// (with `source` badge), tickets with QR to the public verify URL, and the
/// P10 / P50 / P90 release prediction.
class PassportDetailScreen extends StatefulWidget {
  const PassportDetailScreen({super.key, required this.initial});
  final ShipmentPassport initial;

  @override
  State<PassportDetailScreen> createState() => _PassportDetailScreenState();
}

class _PassportDetailScreenState extends State<PassportDetailScreen> {
  late ShipmentPassport _p = widget.initial;
  bool _loading = false;
  bool _offline = false;
  DateTime? _updated;
  String? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final p = await context.read<CargoState>().fetchPassport(_p.id);
      if (!mounted) return;
      setState(() {
        _p = p;
        _updated = DateTime.now();
        _offline = false;
      });
    } on NetworkException {
      if (mounted) setState(() => _offline = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<AppSettings>();
    final l = settings.l10n;
    final p = _p;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(p.reference),
        actions: [
          IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: l.t('refresh'),
              onPressed: _loading ? null : _refresh),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (_error != null) ErrorBanner(_error!, onRetry: _refresh),
            if (_offline)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(l.t('offline_cached'), style: const TextStyle(color: Colors.orange)),
              ),
            Text(p.description, style: theme.textTheme.titleLarge),
            Text('${p.origin} -> ${p.destination}', style: theme.textTheme.bodyLarge),
            const SizedBox(height: 4),
            Wrap(
              spacing: 8,
              runSpacing: 4,
              children: [
                Chip(label: Text(p.cargoType)),
                Chip(label: Text('${l.t('declared')}: ${fmtKg(p.declaredMassKg)} kg')),
                if (p.vgmKg != null) Chip(label: Text('VGM ${fmtKg(p.vgmKg!)} kg')),
                Chip(
                  avatar: const Icon(Icons.local_shipping, size: 16),
                  label: Text(p.vehiclePlate ?? l.t('not_assigned')),
                ),
              ],
            ),
            if (_updated != null)
              Text(l.t('last_updated', {'age': l.age(DateTime.now().difference(_updated!))}),
                  style: theme.textTheme.bodySmall),

            _Section(l.t('stage')),
            _StageTimeline(p: p, l: l),

            _Section(l.t('outstanding')),
            if (p.outstanding.isEmpty)
              Text(l.t('nothing_outstanding'))
            else
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: p.outstanding
                    .map((o) => Chip(
                          avatar: const Icon(Icons.hourglass_empty, size: 16),
                          label: Text(kShipmentStages.contains(o) ? l.stage(o) : o),
                        ))
                    .toList(),
              ),

            _Section(l.t('predicted_release')),
            if (p.predictedReleaseAt == null &&
                p.predictedReleaseP10 == null &&
                p.predictedReleaseP90 == null)
              Text(l.t('no_prediction'))
            else ...[
              _kv(l.t('p10'), fmtLocal(p.predictedReleaseP10)),
              _kv(l.t('p50'), fmtLocal(p.predictedReleaseAt)),
              _kv(l.t('p90'), fmtLocal(p.predictedReleaseP90)),
              if (p.predictionExplanation != null && !settings.lowBandwidth)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    p.predictionExplanation!.entries.map((e) => '${e.key}: ${e.value}').join('\n'),
                    style: theme.textTheme.bodySmall,
                  ),
                ),
            ],

            _Section(l.t('weighings')),
            if (p.weighings.isEmpty)
              Text(l.t('no_weighings'))
            else
              ...p.weighings.map((w) => ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: _DecisionDot(w.decision),
                    title: Text('${fmtTonnes(w.gvmKg)} t  (U ${fmtKg(w.uKg)} kg)  ${w.decision ?? ''}'),
                    subtitle: Text(fmtLocal(w.occurredAt)),
                    trailing: SourceBadge(w.source),
                  )),

            _Section(l.t('tickets')),
            if (p.tickets.isEmpty)
              Text(l.t('no_tickets'))
            else
              ...p.tickets.map((t) => _TicketCard(t: t, settings: settings)),

            if (p.containers.isNotEmpty) ...[
              _Section(l.t('containers')),
              ...p.containers.map((c) =>
                  Text('${c['number']}  ${c['size_ft']} ft  ${c['type']}')),
            ],
            if (p.seals.isNotEmpty) ...[
              _Section(l.t('seals')),
              ...p.seals.map((s) => Text('${s['seal_id']}  ${s['status']}  (${s['provider']})')),
            ],

            _Section(l.t('history')),
            ...p.processingEvents.map((e) => ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.history, size: 18),
                  title: Text('${l.stage(e.stage)} - ${e.status}'),
                  subtitle: Text('${fmtLocal(e.occurredAt)}  ${e.source}${e.notes == null ? '' : '  ${e.notes}'}'),
                )),
            const SizedBox(height: 32),
          ],
        ),
      ),
    );
  }

  Widget _kv(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          children: [
            SizedBox(width: 150, child: Text(k)),
            Text(v, style: const TextStyle(fontWeight: FontWeight.w600)),
          ],
        ),
      );
}

class _Section extends StatelessWidget {
  const _Section(this.title);
  final String title;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 20, bottom: 6),
        child: Text(title.toUpperCase(),
            style: Theme.of(context)
                .textTheme
                .labelLarge
                ?.copyWith(letterSpacing: 1.2, color: Theme.of(context).colorScheme.primary)),
      );
}

class _StageTimeline extends StatelessWidget {
  const _StageTimeline({required this.p, required this.l});
  final ShipmentPassport p;
  final L10n l;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final idx = p.stageIndex;
    return Column(
      children: [
        for (var i = 0; i < kShipmentStages.length; i++)
          Row(
            children: [
              Icon(
                i < idx
                    ? Icons.check_circle
                    : (i == idx ? Icons.radio_button_checked : Icons.radio_button_off),
                size: 20,
                color: i <= idx ? cs.primary : cs.outline,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  l.stage(kShipmentStages[i]),
                  style: TextStyle(
                    fontWeight: i == idx ? FontWeight.bold : FontWeight.normal,
                    color: i <= idx ? cs.onSurface : cs.outline,
                  ),
                ),
              ),
            ],
          ),
      ],
    );
  }
}

class _DecisionDot extends StatelessWidget {
  const _DecisionDot(this.decision);
  final String? decision;

  @override
  Widget build(BuildContext context) {
    final c = switch (decision?.toUpperCase()) {
      'GREEN' => const Color(0xFF00C853),
      'AMBER' => const Color(0xFFFFC400),
      'RED' => const Color(0xFFD50000),
      _ => Colors.grey,
    };
    return Icon(Icons.circle, color: c, size: 18);
  }
}

class _TicketCard extends StatelessWidget {
  const _TicketCard({required this.t, required this.settings});
  final PassportTicket t;
  final AppSettings settings;

  @override
  Widget build(BuildContext context) {
    final l = settings.l10n;
    final url = settings.verifyUrl(t.qrToken);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    t.type == 'static_certified'
                        ? l.t('ticket_static_certified')
                        : l.t('ticket_prescreen'),
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ),
                SourceBadge(t.source),
              ],
            ),
            Text('${t.decision ?? ''}  ${fmtTonnes(t.gvmKg)} t'),
            const SizedBox(height: 8),
            if (!settings.lowBandwidth)
              Center(
                child: QrImageView(
                  data: url,
                  size: 180,
                  backgroundColor: Colors.white,
                ),
              ),
            const SizedBox(height: 6),
            Text(l.t('verify_url'), style: Theme.of(context).textTheme.labelSmall),
            SelectableText(url, style: Theme.of(context).textTheme.bodySmall),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                icon: const Icon(Icons.verified_outlined),
                label: Text(l.t('verify')),
                onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                    builder: (_) => TicketVerifyScreen(initialToken: t.qrToken))),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
