import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/format.dart';
import '../l10n/strings.dart';
import '../models/shipment.dart';
import '../state/app_settings.dart';
import '../state/auth_state.dart';
import '../state/cargo_state.dart';
import '../widgets/error_banner.dart';
import '../widgets/last_updated.dart';
import 'passport_detail_screen.dart';
import 'register_shipment_screen.dart';

class ShipmentListScreen extends StatelessWidget {
  const ShipmentListScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final cargo = context.watch<CargoState>();
    final auth = context.watch<AuthState>();
    return Scaffold(
      appBar: AppBar(
        title: Text(l.t('shipments')),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: l.t('sign_out'),
            onPressed: auth.logout,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
            builder: (_) => ChangeNotifierProvider.value(
                value: cargo, child: const RegisterShipmentScreen()))),
        icon: const Icon(Icons.add),
        label: Text(l.t('register_shipment')),
      ),
      body: Column(
        children: [
          if (cargo.error != null)
            ErrorBanner(cargo.error!, onRetry: cargo.loadShipments),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Row(
              children: [
                Expanded(
                    child: Text(auth.me?.orgName ?? auth.me?.fullName ?? '',
                        style: Theme.of(context).textTheme.bodyLarge)),
                LastUpdatedLabel(
                    updatedAt: cargo.shipmentsUpdated, offline: cargo.offline),
              ],
            ),
          ),
          Expanded(
            child: RefreshIndicator(
              onRefresh: cargo.loadShipments,
              child: cargo.shipments.isEmpty
                  ? ListView(children: [
                      Padding(
                        padding: const EdgeInsets.all(32),
                        child: Center(
                          child: cargo.loadingShipments
                              ? const CircularProgressIndicator()
                              : Text(l.t('no_shipments')),
                        ),
                      )
                    ])
                  : ListView.separated(
                      padding: const EdgeInsets.only(bottom: 88),
                      itemCount: cargo.shipments.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (ctx, i) =>
                          _ShipmentTile(cargo.shipments[i], l: l),
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ShipmentTile extends StatelessWidget {
  const _ShipmentTile(this.s, {required this.l});
  final ShipmentPassport s;
  final L10n l;

  @override
  Widget build(BuildContext context) {
    final cargo = context.read<CargoState>();
    return ListTile(
      title: Text('${s.reference}  -  ${s.description}',
          maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(
          '${s.origin} -> ${s.destination}  -  ${fmtKg(s.declaredMassKg)} kg\n'
          '${l.t('stage')}: ${l.stage(s.stage)}  -  ${l.t('outstanding')}: ${s.outstanding.length}'),
      isThreeLine: true,
      trailing: Chip(
        label: Text(l.stage(s.stage)),
        visualDensity: VisualDensity.compact,
      ),
      onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => ChangeNotifierProvider.value(
              value: cargo, child: PassportDetailScreen(initial: s)))),
    );
  }
}
