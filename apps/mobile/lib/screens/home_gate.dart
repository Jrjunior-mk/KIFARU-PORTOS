import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_settings.dart';
import '../state/auth_state.dart';
import 'cargo_home_screen.dart';
import 'vehicle_select_screen.dart';

/// Routes a signed-in user by role:
/// * driver (or transporter staff)  -> vehicle selection -> Driver Mode
/// * cargo_owner                     -> cargo-owner tabs
/// * both                            -> chooser
/// * anything else                   -> unsupported notice + sign out
class HomeGate extends StatelessWidget {
  const HomeGate({super.key});

  @override
  Widget build(BuildContext context) {
    final me = context.watch<AuthState>().me;
    if (me == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final driver = me.canUseDriverFlow;
    final cargo = me.isCargoOwner;
    if (driver && cargo) return const _ModeChooser();
    if (driver) return const VehicleSelectScreen();
    if (cargo) return const CargoHomeScreen();
    return _Unsupported(roles: me.roles);
  }
}

class _ModeChooser extends StatelessWidget {
  const _ModeChooser();

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    return Scaffold(
      appBar: AppBar(title: Text(l.t('choose_mode'))),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _BigButton(
              icon: Icons.local_shipping,
              label: l.t('driver_flow'),
              onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => const VehicleSelectScreen())),
            ),
            const SizedBox(height: 24),
            _BigButton(
              icon: Icons.inventory_2,
              label: l.t('cargo_flow'),
              onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => const CargoHomeScreen())),
            ),
          ],
        ),
      ),
    );
  }
}

class _BigButton extends StatelessWidget {
  const _BigButton({required this.icon, required this.label, required this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 96,
        child: FilledButton.icon(
          onPressed: onTap,
          icon: Icon(icon, size: 36),
          label: Text(label, style: const TextStyle(fontSize: 24)),
        ),
      );
}

class _Unsupported extends StatelessWidget {
  const _Unsupported({required this.roles});
  final List<String> roles;

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    return Scaffold(
      appBar: AppBar(title: Text(l.t('app_title'))),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(l.t('role_unsupported', {'roles': roles.join(', ')}),
                  textAlign: TextAlign.center),
              const SizedBox(height: 24),
              OutlinedButton(
                onPressed: () => context.read<AuthState>().logout(),
                child: Text(l.t('sign_out')),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
