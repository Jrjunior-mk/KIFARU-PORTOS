import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_client.dart';
import '../core/cache.dart';
import '../state/app_settings.dart';
import '../state/cargo_state.dart';
import 'notifications_screen.dart';
import 'settings_screen.dart';
import 'shipment_list_screen.dart';
import 'ticket_verify_screen.dart';

/// Cargo-owner shell: Shipments / Inbox / Verify / Settings tabs.
class CargoHomeScreen extends StatelessWidget {
  const CargoHomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<CargoState>(
      create: (ctx) {
        final s = CargoState(
          api: ctx.read<ApiClient>(),
          cache: ctx.read<LocalCache>(),
          settings: ctx.read<AppSettings>(),
        );
        unawaited(s.start());
        return s;
      },
      child: const _CargoTabs(),
    );
  }
}

class _CargoTabs extends StatefulWidget {
  const _CargoTabs();

  @override
  State<_CargoTabs> createState() => _CargoTabsState();
}

class _CargoTabsState extends State<_CargoTabs> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final unread = context.watch<CargoState>().unreadCount;
    return Scaffold(
      body: IndexedStack(
        index: _index,
        children: const [
          ShipmentListScreen(),
          NotificationsScreen(),
          TicketVerifyScreen(),
          SettingsScreen(embedded: true),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          NavigationDestination(
              icon: const Icon(Icons.inventory_2_outlined),
              selectedIcon: const Icon(Icons.inventory_2),
              label: l.t('shipments')),
          NavigationDestination(
              icon: Badge(
                isLabelVisible: unread > 0,
                label: Text('$unread'),
                child: const Icon(Icons.notifications_outlined),
              ),
              selectedIcon: const Icon(Icons.notifications),
              label: l.t('notifications')),
          NavigationDestination(
              icon: const Icon(Icons.qr_code_scanner),
              label: l.t('verify_ticket')),
          NavigationDestination(
              icon: const Icon(Icons.settings_outlined),
              selectedIcon: const Icon(Icons.settings),
              label: l.t('settings')),
        ],
      ),
    );
  }
}
