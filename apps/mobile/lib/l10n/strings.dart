/// Map-based localisation: English (`en`) and Kiswahili (`sw`).
///
/// Every driver-facing string lives here so that the Driver Mode panel and the
/// spoken (TTS) announcements come from the same source in both languages.
/// Placeholders use `{name}` and are substituted by [L10n.t].
class L10n {
  const L10n(this.lang);

  final String lang;

  static const List<String> supported = ['en', 'sw'];

  static String languageName(String code) => code == 'sw' ? 'Kiswahili' : 'English';

  /// BCP-47 tag handed to the TTS engine.
  String get ttsLocale => lang == 'sw' ? 'sw-KE' : 'en-GB';

  String t(String key, [Map<String, Object?>? params]) {
    var s = _strings[lang]?[key] ?? _strings['en']?[key] ?? key;
    if (params != null) {
      params.forEach((k, v) {
        s = s.replaceAll('{$k}', '${v ?? ''}');
      });
    }
    return s;
  }

  String decision(String? d) {
    switch (d?.toUpperCase()) {
      case 'GREEN':
        return t('decision_green');
      case 'AMBER':
        return t('decision_amber');
      case 'RED':
        return t('decision_red');
      default:
        return t('awaiting_decision');
    }
  }

  String stage(String s) => t('stage_$s');

  String source(String s) {
    switch (s.toLowerCase()) {
      case 'live':
        return t('source_live');
      case 'simulated':
        return t('source_simulated');
      case 'replay':
        return t('source_replay');
      default:
        return s.toUpperCase();
    }
  }

  /// Human "x ago" string for cached-data ages.
  String age(Duration d) {
    if (d.inSeconds < 45) return t('just_now');
    if (d.inMinutes < 60) return t('minutes_ago', {'n': d.inMinutes});
    if (d.inHours < 24) return t('hours_ago', {'n': d.inHours});
    return t('days_ago', {'n': d.inDays});
  }

  static const Map<String, Map<String, String>> _strings = {
    'en': {
      // ---- common
      'app_title': 'KIFARU PORTOS',
      'login_title': 'Sign in',
      'email': 'Email',
      'password': 'Password',
      'totp_code': 'Authenticator code (only if MFA is enabled)',
      'sign_in': 'Sign in',
      'sign_out': 'Sign out',
      'loading': 'Loading...',
      'retry': 'Retry',
      'refresh': 'Refresh',
      'offline_cached': 'Offline - showing cached data',
      'last_updated': 'Updated {age}',
      'just_now': 'just now',
      'minutes_ago': '{n} min ago',
      'hours_ago': '{n} h ago',
      'days_ago': '{n} d ago',
      'never_updated': 'Not yet updated',
      'source_live': 'LIVE',
      'source_simulated': 'SIMULATED',
      'source_replay': 'REPLAY',
      'role_unsupported':
          'This app supports driver and cargo-owner accounts. Your roles: {roles}.',
      'choose_mode': 'Choose how to use the app',
      'driver_flow': 'Driver',
      'cargo_flow': 'Cargo owner',
      'error_generic': 'Something went wrong',
      'network_error': 'No connection to the server',
      'required': 'Required',
      'invalid_number': 'Enter a whole number',
      'save': 'Save',
      'saved': 'Saved',
      'cancel': 'Cancel',
      'close': 'Close',
      'yes': 'Yes',
      'no': 'No',
      // ---- driver
      'select_vehicle': 'Select your vehicle',
      'no_vehicles': 'No vehicles found for your organisation.',
      'enter_driver_mode': 'Enter driver mode',
      'book_slot': 'Book a slot',
      'driver_mode_notice':
          'Driver mode has no buttons. Hold anywhere on the screen for 2 seconds to exit. Keep your eyes on the road; decisions are spoken aloud.',
      'location_needed':
          'Location permission is needed to send your position every minute while driver mode is open.',
      'exit_hint': 'Hold to exit driver mode',
      'keep_holding': 'Keep holding...',
      'appointment': 'Appointment',
      'no_appointment': 'No slot booked',
      'slot_in': 'Slot in {m} min',
      'slot_in_hours': 'Slot in {h} h {m} min',
      'slot_now': 'Slot is open now',
      'slot_passed': 'Slot passed {m} min ago',
      'queue': 'Queue',
      'trucks_waiting': '{n} trucks waiting',
      'avg_wait': '~{m} min wait',
      'station_operational': 'Station operational',
      'station_degraded': 'Station degraded',
      'station_offline': 'Station offline',
      'latest_clearance': 'Latest clearance',
      'awaiting_decision': 'AWAITING',
      'decision_green': 'GREEN',
      'decision_amber': 'AMBER',
      'decision_red': 'RED',
      'instr_continue': 'Continue',
      'instr_static_scale': 'Proceed to static scale - lane {lane}',
      'instr_static_scale_nolane': 'Proceed to static scale',
      'instr_stop': 'Stop for inspection',
      'instr_awaiting': 'Drive on; await decision',
      'gvm': 'GVM {t} t',
      'gps_idle': 'GPS starting',
      'gps_sent': 'GPS sent',
      'gps_queued': 'GPS queued ({n})',
      'gps_denied': 'Location permission denied',
      'gps_error': 'GPS unavailable',
      'live_connected': 'Live',
      'live_disconnected': 'Reconnecting...',
      'prescreen_note':
          'Pre-screen only - not a legal weight certificate. The static scale remains the reference.',
      'static_certified_note': 'Static scale certified weight',
      'audit_selected': 'Random audit selected',
      // ---- slots
      'stations': 'Stations',
      'slots': 'Available slots (next 6 h)',
      'booked': 'Booked',
      'full': 'Full',
      'slot_booked_ok': 'Slot booked',
      'capacity': '{a} of {c} free',
      // ---- cargo
      'shipments': 'Shipments',
      'no_shipments': 'No shipments yet',
      'register_shipment': 'Register shipment',
      'description': 'Description',
      'origin': 'Origin',
      'destination': 'Destination',
      'declared_mass_kg': 'Declared mass (kg)',
      'cargo_type': 'Cargo type',
      'container_number': 'Container number (ISO 6346, optional)',
      'container_invalid_format': 'Must be 4 letters + 7 digits',
      'container_invalid_check': 'ISO 6346 check digit invalid',
      'container_check_ok': 'Check digit OK',
      'declaration_reference': 'Declaration reference (optional)',
      'seal_id': 'Seal ID (optional)',
      'submit': 'Submit',
      'shipment_registered': 'Shipment {ref} registered',
      'passport': 'Cargo passport',
      'stage': 'Stage',
      'outstanding': 'Outstanding',
      'nothing_outstanding': 'Nothing outstanding',
      'weighings': 'Weighings',
      'no_weighings': 'No weighings yet',
      'tickets': 'Tickets',
      'no_tickets': 'No tickets yet',
      'ticket_prescreen': 'Pre-screen ticket',
      'ticket_static_certified': 'Static certified ticket',
      'predicted_release': 'Predicted release',
      'p10': 'Early (P10)',
      'p50': 'Expected (P50)',
      'p90': 'Late (P90)',
      'no_prediction': 'No prediction yet',
      'verify_url': 'Public verification link',
      'declared': 'Declared',
      'vehicle': 'Vehicle',
      'not_assigned': 'Not assigned',
      'containers': 'Containers',
      'seals': 'Seals',
      'history': 'History',
      // ---- notifications
      'notifications': 'Inbox',
      'no_notifications': 'No notifications',
      'mark_read': 'Mark read',
      // ---- verify
      'verify_ticket': 'Verify ticket',
      'qr_token': 'QR token',
      'verify': 'Verify',
      'ticket_valid': 'VALID',
      'ticket_invalid': 'NOT VALID',
      'ticket_not_found': 'No ticket found for this token',
      'legal_status': 'Legal status',
      'evidence_hash': 'Evidence hash',
      // ---- settings
      'settings': 'Settings',
      'api_url': 'API base URL',
      'api_url_hint': 'e.g. https://api.kifaru.example or http://10.0.2.2:8000',
      'public_base_url': 'Public verify base URL (QR links)',
      'language': 'Language',
      'low_bandwidth': 'Low-bandwidth mode',
      'low_bandwidth_hint': 'Text only, no QR images, fewer background updates',
      'tts_mode': 'Spoken announcements',
      'tts_both': 'Kiswahili + English',
      'tts_en': 'English only',
      'tts_sw': 'Kiswahili only',
      'relogin_hint': 'Changing the API URL signs you out.',
      'about_not_compiled':
          'Build info: see README. Every value on screen comes from the API; simulated data is always labelled.',
      // ---- stages
      'stage_registered': 'Registered',
      'stage_declared': 'Declared',
      'stage_at_port': 'At port',
      'stage_customs_processing': 'Customs',
      'stage_weighing_verification': 'Weighing',
      'stage_gate_processing': 'Gate',
      'stage_released': 'Released',
      'stage_in_transit': 'In transit',
      'stage_delivered': 'Delivered',
      'stage_closed': 'Closed',
    },
    'sw': {
      // ---- common
      'app_title': 'KIFARU PORTOS',
      'login_title': 'Ingia',
      'email': 'Barua pepe',
      'password': 'Nenosiri',
      'totp_code': 'Nambari ya uthibitishaji (ikiwa MFA imewezeshwa tu)',
      'sign_in': 'Ingia',
      'sign_out': 'Toka',
      'loading': 'Inapakia...',
      'retry': 'Jaribu tena',
      'refresh': 'Sasisha',
      'offline_cached': 'Hakuna mtandao - data iliyohifadhiwa',
      'last_updated': 'Imesasishwa {age}',
      'just_now': 'sasa hivi',
      'minutes_ago': 'dakika {n} zilizopita',
      'hours_ago': 'saa {n} zilizopita',
      'days_ago': 'siku {n} zilizopita',
      'never_updated': 'Bado haijasasishwa',
      'source_live': 'HALISI',
      'source_simulated': 'ILIYOIGIZWA',
      'source_replay': 'RUDIO',
      'role_unsupported':
          'Programu hii ni ya akaunti za dereva na mmiliki wa mizigo. Nafasi zako: {roles}.',
      'choose_mode': 'Chagua jinsi ya kutumia programu',
      'driver_flow': 'Dereva',
      'cargo_flow': 'Mmiliki wa mizigo',
      'error_generic': 'Hitilafu imetokea',
      'network_error': 'Hakuna muunganisho na seva',
      'required': 'Inahitajika',
      'invalid_number': 'Weka nambari kamili',
      'save': 'Hifadhi',
      'saved': 'Imehifadhiwa',
      'cancel': 'Ghairi',
      'close': 'Funga',
      'yes': 'Ndiyo',
      'no': 'Hapana',
      // ---- driver
      'select_vehicle': 'Chagua gari lako',
      'no_vehicles': 'Hakuna magari yaliyopatikana kwa shirika lako.',
      'enter_driver_mode': 'Ingia hali ya dereva',
      'book_slot': 'Weka nafasi',
      'driver_mode_notice':
          'Hali ya dereva haina vitufe. Shikilia skrini sekunde 2 kutoka. Angalia barabara; maamuzi yanatangazwa kwa sauti.',
      'location_needed':
          'Ruhusa ya mahali inahitajika kutuma eneo lako kila dakika wakati hali ya dereva iko wazi.',
      'exit_hint': 'Shikilia kutoka hali ya dereva',
      'keep_holding': 'Endelea kushikilia...',
      'appointment': 'Miadi',
      'no_appointment': 'Hakuna nafasi iliyowekwa',
      'slot_in': 'Nafasi baada ya dakika {m}',
      'slot_in_hours': 'Nafasi baada ya saa {h} dakika {m}',
      'slot_now': 'Nafasi iko wazi sasa',
      'slot_passed': 'Nafasi ilipita dakika {m} zilizopita',
      'queue': 'Foleni',
      'trucks_waiting': 'Malori {n} yanasubiri',
      'avg_wait': 'Subiri ~dakika {m}',
      'station_operational': 'Kituo kinafanya kazi',
      'station_degraded': 'Kituo kina hitilafu',
      'station_offline': 'Kituo kimefungwa',
      'latest_clearance': 'Uamuzi wa hivi karibuni',
      'awaiting_decision': 'INASUBIRI',
      'decision_green': 'KIJANI',
      'decision_amber': 'MANJANO',
      'decision_red': 'NYEKUNDU',
      'instr_continue': 'Endelea',
      'instr_static_scale': 'Nenda kwenye mizani ya kusimama - njia {lane}',
      'instr_static_scale_nolane': 'Nenda kwenye mizani ya kusimama',
      'instr_stop': 'Simama kwa ukaguzi',
      'instr_awaiting': 'Endelea; subiri uamuzi',
      'gvm': 'Uzito {t} t',
      'gps_idle': 'GPS inaanza',
      'gps_sent': 'GPS imetumwa',
      'gps_queued': 'GPS imehifadhiwa ({n})',
      'gps_denied': 'Ruhusa ya mahali imekataliwa',
      'gps_error': 'GPS haipatikani',
      'live_connected': 'Moja kwa moja',
      'live_disconnected': 'Inaunganisha tena...',
      'prescreen_note':
          'Ukaguzi wa awali tu - si cheti halali cha uzito. Mizani ya kusimama ndiyo kipimo rasmi.',
      'static_certified_note': 'Uzito uliothibitishwa na mizani ya kusimama',
      'audit_selected': 'Umechaguliwa kwa ukaguzi wa nasibu',
      // ---- slots
      'stations': 'Vituo',
      'slots': 'Nafasi zilizopo (saa 6 zijazo)',
      'booked': 'Imewekwa',
      'full': 'Imejaa',
      'slot_booked_ok': 'Nafasi imewekwa',
      'capacity': '{a} kati ya {c} wazi',
      // ---- cargo
      'shipments': 'Mizigo',
      'no_shipments': 'Bado hakuna mizigo',
      'register_shipment': 'Sajili mzigo',
      'description': 'Maelezo',
      'origin': 'Kutoka',
      'destination': 'Kwenda',
      'declared_mass_kg': 'Uzito uliotangazwa (kg)',
      'cargo_type': 'Aina ya mzigo',
      'container_number': 'Nambari ya kontena (ISO 6346, hiari)',
      'container_invalid_format': 'Lazima iwe herufi 4 + tarakimu 7',
      'container_invalid_check': 'Tarakimu ya ukaguzi ISO 6346 si sahihi',
      'container_check_ok': 'Tarakimu ya ukaguzi ni sahihi',
      'declaration_reference': 'Nambari ya tamko (hiari)',
      'seal_id': 'Nambari ya lakiri (hiari)',
      'submit': 'Tuma',
      'shipment_registered': 'Mzigo {ref} umesajiliwa',
      'passport': 'Pasipoti ya mzigo',
      'stage': 'Hatua',
      'outstanding': 'Yanayosubiri',
      'nothing_outstanding': 'Hakuna kinachosubiri',
      'weighings': 'Vipimo',
      'no_weighings': 'Bado hakuna vipimo',
      'tickets': 'Tiketi',
      'no_tickets': 'Bado hakuna tiketi',
      'ticket_prescreen': 'Tiketi ya ukaguzi wa awali',
      'ticket_static_certified': 'Tiketi iliyothibitishwa',
      'predicted_release': 'Utolewaji unaotarajiwa',
      'p10': 'Mapema (P10)',
      'p50': 'Inatarajiwa (P50)',
      'p90': 'Kuchelewa (P90)',
      'no_prediction': 'Bado hakuna utabiri',
      'verify_url': 'Kiungo cha uthibitishaji cha umma',
      'declared': 'Imetangazwa',
      'vehicle': 'Gari',
      'not_assigned': 'Halijapangiwa',
      'containers': 'Makontena',
      'seals': 'Lakiri',
      'history': 'Historia',
      // ---- notifications
      'notifications': 'Arifa',
      'no_notifications': 'Hakuna arifa',
      'mark_read': 'Weka imesomwa',
      // ---- verify
      'verify_ticket': 'Thibitisha tiketi',
      'qr_token': 'Tokeni ya QR',
      'verify': 'Thibitisha',
      'ticket_valid': 'HALALI',
      'ticket_invalid': 'SI HALALI',
      'ticket_not_found': 'Hakuna tiketi kwa tokeni hii',
      'legal_status': 'Hali ya kisheria',
      'evidence_hash': 'Hashi ya ushahidi',
      // ---- settings
      'settings': 'Mipangilio',
      'api_url': 'Anwani ya API',
      'api_url_hint': 'mf. https://api.kifaru.example au http://10.0.2.2:8000',
      'public_base_url': 'Anwani ya uthibitishaji ya umma (viungo vya QR)',
      'language': 'Lugha',
      'low_bandwidth': 'Hali ya mtandao hafifu',
      'low_bandwidth_hint': 'Maandishi tu, hakuna picha za QR, masasisho machache',
      'tts_mode': 'Matangazo ya sauti',
      'tts_both': 'Kiswahili + Kiingereza',
      'tts_en': 'Kiingereza tu',
      'tts_sw': 'Kiswahili tu',
      'relogin_hint': 'Kubadilisha anwani ya API kunakutoa.',
      'about_not_compiled':
          'Maelezo ya ujenzi: tazama README. Kila thamani inatoka kwa API; data iliyoigizwa huwekwa alama daima.',
      // ---- stages
      'stage_registered': 'Imesajiliwa',
      'stage_declared': 'Imetangazwa',
      'stage_at_port': 'Bandarini',
      'stage_customs_processing': 'Forodha',
      'stage_weighing_verification': 'Upimaji',
      'stage_gate_processing': 'Lango',
      'stage_released': 'Imetolewa',
      'stage_in_transit': 'Safarini',
      'stage_delivered': 'Imefikishwa',
      'stage_closed': 'Imefungwa',
    },
  };
}
