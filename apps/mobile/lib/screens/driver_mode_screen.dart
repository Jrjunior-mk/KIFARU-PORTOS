import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../core/api_client.dart';
import '../core/cache.dart';
import '../core/decision_instruction.dart';
import '../core/format.dart';
import '../l10n/strings.dart';
import '../models/vehicle.dart';
import '../state/app_settings.dart';
import '../state/driver_state.dart';
import '../widgets/source_badge.dart';

/// Hands-free, full-screen Driver Mode.
///
/// Design rules (see README, "never touch the phone while driving"):
/// * no buttons, no scrolling, no dialogs;
/// * extra-large, high-contrast text on black;
/// * the only gesture is a 2-second hold anywhere to exit;
/// * decisions are spoken aloud; the screen stays awake;
/// * data refreshes by WebSocket push, with 30 s polling as fallback.
class DriverModeScreen extends StatelessWidget {
  const DriverModeScreen({super.key, required this.vehicle});
  final Vehicle vehicle;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<DriverState>(
      create: (ctx) {
        final s = DriverState(
          api: ctx.read<ApiClient>(),
          cache: ctx.read<LocalCache>(),
          settings: ctx.read<AppSettings>(),
          vehicle: vehicle,
        );
        unawaited(s.start());
        return s;
      },
      child: const _DriverModeBody(),
    );
  }
}

class _DriverModeBody extends StatefulWidget {
  const _DriverModeBody();

  @override
  State<_DriverModeBody> createState() => _DriverModeBodyState();
}

class _DriverModeBodyState extends State<_DriverModeBody> {
  static const holdToExit = Duration(milliseconds: 1500);
  Timer? _hold;
  bool _holding = false;

  @override
  void initState() {
    super.initState();
    unawaited(WakelockPlus.enable());
    unawaited(SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky));
  }

  @override
  void dispose() {
    _hold?.cancel();
    unawaited(WakelockPlus.disable());
    unawaited(SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge));
    super.dispose();
  }

  void _startHold() {
    _hold?.cancel();
    setState(() => _holding = true);
    _hold = Timer(holdToExit, () {
      if (mounted) Navigator.of(context).pop();
    });
  }

  void _cancelHold() {
    _hold?.cancel();
    if (mounted) setState(() => _holding = false);
  }

  @override
  Widget build(BuildContext context) {
    final settings = context.watch<AppSettings>();
    final l = settings.l10n;
    final st = context.watch<DriverState>();

    return PopScope(
      canPop: false, // back button must not exit accidentally; hold instead
      child: Scaffold(
        backgroundColor: Colors.black,
        body: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onLongPressStart: (_) => _startHold(),
          onLongPressEnd: (_) => _cancelHold(),
          onLongPressCancel: _cancelHold,
          child: SafeArea(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _TopBar(state: st, l: l),
                _AppointmentRow(state: st, l: l),
                _QueueRow(state: st, l: l),
                Expanded(child: _DecisionPanel(state: st, l: l, lowBandwidth: settings.lowBandwidth)),
                _ExitHint(holding: _holding, l: l),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// --------------------------------------------------------------------------- pieces

const _dim = Color(0xFFB0BEC5);

class _TopBar extends StatelessWidget {
  const _TopBar({required this.state, required this.l});
  final DriverState state;
  final L10n l;

  @override
  Widget build(BuildContext context) {
    final gps = switch (state.gpsStatus) {
      'sent' => l.t('gps_sent'),
      'queued' => l.t('gps_queued', {'n': state.queuedPositions}),
      'denied' => l.t('gps_denied'),
      'error' => l.t('gps_error'),
      _ => l.t('gps_idle'),
    };
    final updated = state.lastUpdated == null
        ? l.t('never_updated')
        : l.t('last_updated',
            {'age': l.age(DateTime.now().difference(state.lastUpdated!))});
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
      child: Row(
        children: [
          Text(state.vehicle.plate,
              style: const TextStyle(
                  color: Colors.white, fontSize: 28, fontWeight: FontWeight.w800)),
          const Spacer(),
          Icon(Icons.circle,
              size: 14,
              color: state.wsConnected
                  ? const Color(0xFF00E676)
                  : (state.offline ? Colors.redAccent : Colors.orange)),
          const SizedBox(width: 6),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                state.offline
                    ? l.t('offline_cached')
                    : (state.wsConnected ? l.t('live_connected') : l.t('live_disconnected')),
                style: TextStyle(
                    color: state.offline ? Colors.orange : _dim, fontSize: 14),
              ),
              Text('$updated - $gps',
                  style: const TextStyle(color: _dim, fontSize: 13)),
            ],
          ),
        ],
      ),
    );
  }
}

class _AppointmentRow extends StatelessWidget {
  const _AppointmentRow({required this.state, required this.l});
  final DriverState state;
  final L10n l;

  @override
  Widget build(BuildContext context) {
    final a = state.appointment;
    String headline;
    String detail;
    if (a == null) {
      headline = l.t('no_appointment');
      detail = '';
    } else {
      final d = a.slotStart.difference(state.now);
      final inSlot = !state.now.isBefore(a.slotStart) && state.now.isBefore(a.slotEnd);
      if (inSlot) {
        headline = l.t('slot_now');
      } else if (d.isNegative) {
        headline = l.t('slot_passed', {'m': (-d.inMinutes)});
      } else if (d.inHours >= 1) {
        headline = l.t('slot_in_hours', {'h': d.inHours, 'm': d.inMinutes % 60});
      } else {
        headline = l.t('slot_in', {'m': d.inMinutes + 1});
      }
      detail = '${a.stationCode}  ${fmtLocal(a.slotStart)} - ${fmtLocal(a.slotEnd, withDate: false)}';
    }
    return _Block(
      label: l.t('appointment'),
      headline: headline,
      detail: detail,
    );
  }
}

class _QueueRow extends StatelessWidget {
  const _QueueRow({required this.state, required this.l});
  final DriverState state;
  final L10n l;

  @override
  Widget build(BuildContext context) {
    final s = state.station;
    if (s == null) return const SizedBox(height: 8);
    final statusKey = switch (s.status) {
      'degraded' => 'station_degraded',
      'offline' => 'station_offline',
      _ => 'station_operational',
    };
    return _Block(
      label: '${l.t('queue')} - ${s.code}',
      headline:
          '${l.t('trucks_waiting', {'n': s.queueLen})}  -  ${l.t('avg_wait', {'m': (s.avgWaitS / 60).round()})}',
      detail: l.t(statusKey),
      detailColor: s.status == 'operational' ? _dim : Colors.orange,
    );
  }
}

class _Block extends StatelessWidget {
  const _Block({
    required this.label,
    required this.headline,
    required this.detail,
    this.detailColor = _dim,
  });
  final String label;
  final String headline;
  final String detail;
  final Color detailColor;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label.toUpperCase(),
                style: const TextStyle(color: _dim, fontSize: 14, letterSpacing: 1.5)),
            Text(headline,
                maxLines: 2,
                style: const TextStyle(
                    color: Colors.white, fontSize: 30, fontWeight: FontWeight.w700, height: 1.1)),
            if (detail.isNotEmpty)
              Text(detail, style: TextStyle(color: detailColor, fontSize: 18)),
          ],
        ),
      );
}

class _DecisionPanel extends StatelessWidget {
  const _DecisionPanel({required this.state, required this.l, required this.lowBandwidth});
  final DriverState state;
  final L10n l;
  final bool lowBandwidth;

  @override
  Widget build(BuildContext context) {
    final ins = state.instruction;
    final d = state.decision;
    final ev = state.latest;
    final (bg, fg) = switch (ins.clearance) {
      Clearance.green => (const Color(0xFF00C853), Colors.black),
      Clearance.amber => (const Color(0xFFFFC400), Colors.black),
      Clearance.red => (const Color(0xFFD50000), Colors.white),
      Clearance.unknown => (const Color(0xFF37474F), Colors.white),
    };
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 4, 12, 4),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(24)),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(l.t('latest_clearance').toUpperCase(),
              textAlign: TextAlign.center,
              style: TextStyle(color: fg, fontSize: 16, letterSpacing: 2)),
          const SizedBox(height: 8),
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              l.decision(d?.decision),
              style: TextStyle(color: fg, fontSize: 110, fontWeight: FontWeight.w900, height: 1.0),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            l.t(ins.key, ins.params),
            textAlign: TextAlign.center,
            style: TextStyle(color: fg, fontSize: 40, fontWeight: FontWeight.w700, height: 1.1),
          ),
          const SizedBox(height: 16),
          if (ev != null) ...[
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(l.t('gvm', {'t': fmtTonnes(ev.gvmKg)}),
                    style: TextStyle(color: fg, fontSize: 26, fontWeight: FontWeight.w600)),
                const SizedBox(width: 12),
                Text(fmtLocal(ev.occurredAt, withDate: false),
                    style: TextStyle(color: fg, fontSize: 22)),
                const SizedBox(width: 12),
                SourceBadge(ev.source, large: true),
              ],
            ),
            const SizedBox(height: 8),
            if (d?.auditSelected ?? false)
              Text(l.t('audit_selected'),
                  textAlign: TextAlign.center,
                  style: TextStyle(color: fg, fontSize: 18)),
            if (!lowBandwidth)
              Text(
                d?.ticketType == 'static_certified'
                    ? l.t('static_certified_note')
                    : l.t('prescreen_note'),
                textAlign: TextAlign.center,
                style: TextStyle(color: fg, fontSize: 14),
              ),
          ],
        ],
      ),
    );
  }
}

class _ExitHint extends StatelessWidget {
  const _ExitHint({required this.holding, required this.l});
  final bool holding;
  final L10n l;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 6, 16, 10),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.touch_app, color: holding ? Colors.white : _dim, size: 18),
            const SizedBox(width: 8),
            Text(holding ? l.t('keep_holding') : l.t('exit_hint'),
                style: TextStyle(color: holding ? Colors.white : _dim, fontSize: 15)),
          ],
        ),
      );
}
