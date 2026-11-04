import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api_exceptions.dart';
import '../core/iso6346.dart';
import '../state/app_settings.dart';
import '../state/cargo_state.dart';
import '../widgets/error_banner.dart';
import 'passport_detail_screen.dart';

const _cargoTypes = ['general', 'container', 'bulk', 'liquid', 'reefer', 'hazardous'];

/// `POST /shipments` with client-side ISO 6346 validation of the container
/// number (the API validates again server-side; 422 is surfaced per field).
class RegisterShipmentScreen extends StatefulWidget {
  const RegisterShipmentScreen({super.key});

  @override
  State<RegisterShipmentScreen> createState() => _RegisterShipmentScreenState();
}

class _RegisterShipmentScreenState extends State<RegisterShipmentScreen> {
  final _form = GlobalKey<FormState>();
  final _description = TextEditingController();
  final _origin = TextEditingController();
  final _destination = TextEditingController();
  final _mass = TextEditingController();
  final _container = TextEditingController();
  final _declaration = TextEditingController();
  final _seal = TextEditingController();
  String _cargoType = 'general';
  bool _busy = false;
  String? _error;
  ValidationException? _serverErrors;

  @override
  void dispose() {
    for (final c in [_description, _origin, _destination, _mass, _container, _declaration, _seal]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _error = null;
      _serverErrors = null;
    });
    if (!(_form.currentState?.validate() ?? false)) return;
    final l = context.read<AppSettings>().l10n;
    final cargo = context.read<CargoState>();
    final container = Iso6346.normalise(_container.text);
    final body = <String, dynamic>{
      'description': _description.text.trim(),
      'cargo_type': _cargoType,
      'origin': _origin.text.trim(),
      'destination': _destination.text.trim(),
      'declared_mass_kg': int.parse(_mass.text.trim()),
      if (container.isNotEmpty)
        'containers': [
          {'number': container, 'size_ft': 40, 'type': 'GP'}
        ],
      if (_declaration.text.trim().isNotEmpty)
        'declaration_reference': _declaration.text.trim(),
      if (_seal.text.trim().isNotEmpty) 'seal_id': _seal.text.trim(),
    };
    setState(() => _busy = true);
    try {
      final p = await cargo.register(body);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(l.t('shipment_registered', {'ref': p.reference}))));
      Navigator.of(context).pushReplacement(MaterialPageRoute<void>(
          builder: (_) => ChangeNotifierProvider.value(
              value: cargo, child: PassportDetailScreen(initial: p))));
    } on ValidationException catch (e) {
      setState(() {
        _serverErrors = e;
        _error = e.detail;
      });
      _form.currentState?.validate();
    } on ApiException catch (e) {
      setState(() => _error = e.detail);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _required(String? v, String l) => (v == null || v.trim().isEmpty) ? l : null;

  @override
  Widget build(BuildContext context) {
    final l = context.watch<AppSettings>().l10n;
    final cd = Iso6346.normalise(_container.text).isEmpty
        ? null
        : Iso6346.validationError(_container.text);
    return Scaffold(
      appBar: AppBar(title: Text(l.t('register_shipment'))),
      body: Column(
        children: [
          if (_error != null) ErrorBanner(_error!),
          Expanded(
            child: Form(
              key: _form,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  TextFormField(
                    controller: _description,
                    decoration: InputDecoration(
                        labelText: l.t('description'),
                        errorText: _serverErrors?.forField('description')),
                    maxLength: 300,
                    validator: (v) => (v == null || v.trim().length < 3) ? l.t('required') : null,
                  ),
                  DropdownButtonFormField<String>(
                    value: _cargoType,
                    decoration: InputDecoration(labelText: l.t('cargo_type')),
                    items: _cargoTypes
                        .map((t) => DropdownMenuItem(value: t, child: Text(t)))
                        .toList(),
                    onChanged: (v) => setState(() => _cargoType = v ?? 'general'),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _origin,
                    decoration: InputDecoration(
                        labelText: l.t('origin'),
                        errorText: _serverErrors?.forField('origin')),
                    validator: (v) => _required(v, l.t('required')),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _destination,
                    decoration: InputDecoration(
                        labelText: l.t('destination'),
                        errorText: _serverErrors?.forField('destination')),
                    validator: (v) => _required(v, l.t('required')),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _mass,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                        labelText: l.t('declared_mass_kg'),
                        suffixText: 'kg',
                        helperText: '0 - 60 000',
                        errorText: _serverErrors?.forField('declared_mass_kg')),
                    validator: (v) {
                      final n = int.tryParse((v ?? '').trim());
                      if (n == null) return l.t('invalid_number');
                      if (n < 0 || n > 60000) return '0 - 60000';
                      return null;
                    },
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _container,
                    textCapitalization: TextCapitalization.characters,
                    maxLength: 13,
                    decoration: InputDecoration(
                      labelText: l.t('container_number'),
                      hintText: 'CSQU3054383',
                      helperText: cd == null && _container.text.isNotEmpty
                          ? l.t('container_check_ok')
                          : null,
                      errorText: _serverErrors?.forField('number'),
                    ),
                    onChanged: (_) => setState(() {}),
                    validator: (v) {
                      final n = Iso6346.normalise(v ?? '');
                      if (n.isEmpty) return null;
                      final err = Iso6346.validationError(n);
                      return err == null ? null : l.t(err);
                    },
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _declaration,
                    decoration: InputDecoration(labelText: l.t('declaration_reference')),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _seal,
                    decoration: InputDecoration(labelText: l.t('seal_id')),
                  ),
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: _busy
                        ? const SizedBox(
                            height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                        : Text(l.t('submit')),
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
