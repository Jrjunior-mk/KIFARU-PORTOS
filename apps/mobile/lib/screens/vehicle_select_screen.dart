import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/api_exceptions.dart';
import '../core/cache.dart';
import '../core/json_utils.dart';
import '../models/vehicle.dart';
import '../state/app_settings.dart';
import '../state/auth_state.dart';
import '../widgets/error_banner.dart';
import '../widgets/last_updated.dart';
import 'book_slot_screen.dart';
import 'driver_mode_screen.dart';
import 'settings_screen.dart';

/// Pre-drive screen: pick the vehicle, optionally book a slot, then enter
/// Driver Mode. This is the last screen with interactive controls; everything
/// the driver needs while moving is on the next one, hands-free.
class VehicleSelectScreen extends StatefulWidget {
  const VehicleSelectScreen({super.key});

  @override
  State<VehicleSelectScreen> createState() => _VehicleSelectScreenState();
}

class _VehicleSelectScreenState extends State<VehicleSelectScreen> {
  static const _cacheKey = 'fleet.vehicles';
  List<Vehicle> _vehicles = [];
  Vehicle? _selected;
  DateTime? _updated;
  bool _offline = false;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    final cached = context
        .read<LocalCache>()
        .getJson(_cacheKey, (j) => asMapList(j).map(Vehicle.fromJson).toList());
    if (cached != null) {
      _vehicles = cached.value;
      _updated = cached.storedAt;
      _loading = false;
    }
    final lastId = context.read<LocalCache>().prefs.getString('driver.last_vehicle');
    if (lastId != null) {
      for (final v in _vehicles) {
        if (v.id == lastId) _selected = v;
      }
    }
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final api = context.read<ApiClient>();
    final cache = context.read<LocalCache>();
    try {
      final list = asMapList(await api.get('/fleet/vehicles'));
      await cache.putJson(_cacheKey, list);
      if (!mounted) return;
      setState(() {
        _vehicles = list.map(Vehicle.fromJson).toList();
        _updated = DateTime.now();
        _offline = false;
        if (_selected != null) {
          _selected = _vehicles.cast<Vehicle?>().firstWhere(
              (v) => v!.id == _selected!.id,
              orElse: () => null);
        }
      });
    } on NetworkException {
      if (mounted) setState(() => _offline = true);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _enterDriverMode() async {
    final v = _selected;
    if (v == null) return;
    final l = context.read<AppSettings>().l10n;
    await context.read<LocalCache>().prefs.setString('driver.last_vehicle', v.id);
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
    }
    if (!mounted) return;
    if (perm == LocationPermission.denied ||
        perm == LocationPermission.deniedForever) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(l.t('location_needed'))));
    }
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(l.t('enter_driver_mode')),
        content: Text(l.t('driver_mode_notice')),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: Text(l.t('cancel'))),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(l.t('enter_driver_mode'))),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => DriverModeScreen(vehicle: v), fullscreenDialog: true));
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final auth = context.watch<AuthState>();
    return Scaffold(
      appBar: AppBar(
        title: Text(l.t('select_vehicle')),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            tooltip: l.t('settings'),
            onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const SettingsScreen())),
          ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: l.t('sign_out'),
            onPressed: auth.logout,
          ),
        ],
      ),
      body: Column(
        children: [
          if (_error != null) ErrorBanner(_error!, onRetry: _load),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Row(
              children: [
                Expanded(
                  child: Text(auth.me?.fullName ?? '',
                      style: Theme.of(context).textTheme.bodyLarge),
                ),
                LastUpdatedLabel(updatedAt: _updated, offline: _offline),
              ],
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: _load,
              child: _loading && _vehicles.isEmpty
                  ? const Center(child: CircularProgressIndicator())
                  : _vehicles.isEmpty
                      ? ListView(children: [
                          Padding(
                            padding: const EdgeInsets.all(24),
                            child: Text(l.t('no_vehicles'),
                                textAlign: TextAlign.center),
                          )
                        ])
                      : ListView.builder(
                          itemCount: _vehicles.length,
                          itemBuilder: (ctx, i) {
                            final v = _vehicles[i];
                            final sel = v.id == _selected?.id;
                            return ListTile(
                              selected: sel,
                              leading: Icon(sel
                                  ? Icons.radio_button_checked
                                  : Icons.radio_button_off),
                              title: Text(v.plate,
                                  style: const TextStyle(
                                      fontSize: 22,
                                      fontWeight: FontWeight.bold)),
                              subtitle: Text(
                                  '${v.label.isEmpty ? v.bodyType : v.label} - ${v.axleConfig} - ${v.classCode}'),
                              trailing: v.watchlisted
                                  ? const Icon(Icons.flag, color: Colors.red)
                                  : null,
                              onTap: () => setState(() => _selected = v),
                            );
                          },
                        ),
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: _selected == null
                          ? null
                          : () => Navigator.of(context).push(
                                MaterialPageRoute<void>(
                                    builder: (_) =>
                                        BookSlotScreen(vehicle: _selected!)),
                              ),
                      icon: const Icon(Icons.event_available),
                      label: Text(l.t('book_slot')),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    flex: 2,
                    child: SizedBox(
                      height: 56,
                      child: FilledButton.icon(
                        onPressed: _selected == null ? null : _enterDriverMode,
                        icon: const Icon(Icons.drive_eta),
                        label: Text(l.t('enter_driver_mode'),
                            style: const TextStyle(fontSize: 18)),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
