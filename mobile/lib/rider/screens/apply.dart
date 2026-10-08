import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';
import '../../api.dart';
import '../../i18n.dart';
import '../../util.dart';
import '../logic.dart';
import '../session.dart';

/// Take a photo with the camera, or pick one from the gallery. Returns the picture's bytes.
Future<Uint8List?> pickPhoto(BuildContext context, {bool selfie = false}) async {
  final source = await showModalBottomSheet<ImageSource>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(leading: const Icon(Icons.photo_camera_outlined), title: Text(tr('Take a photo')), onTap: () => Navigator.pop(ctx, ImageSource.camera)),
        ListTile(leading: const Icon(Icons.photo_library_outlined), title: Text(tr('Choose from gallery')), onTap: () => Navigator.pop(ctx, ImageSource.gallery)),
      ]),
    ),
  );
  if (source == null) return null;
  try {
    final f = await ImagePicker().pickImage(
      source: source,
      maxWidth: 1600,
      imageQuality: 80,
      preferredCameraDevice: selfie ? CameraDevice.front : CameraDevice.rear,
    );
    return f == null ? null : await f.readAsBytes();
  } catch (_) {
    if (context.mounted) toast(context, tr("That photo couldn't be read. Try again."));
    return null;
  }
}

/// A tappable photo slot with a preview.
class PhotoSlot extends StatelessWidget {
  final String title, hint;
  final IconData icon;
  final Uint8List? bytes;
  final String? error;
  final VoidCallback onTap;
  const PhotoSlot({super.key, required this.title, required this.hint, required this.icon, required this.bytes, required this.error, required this.onTap});

  @override
  Widget build(BuildContext context) => Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(14),
                child: Container(
                  width: 84,
                  height: 84,
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  child: bytes == null ? Icon(icon, size: 30, color: mutedOf(context)) : Image.memory(bytes!, fit: BoxFit.cover),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: kItem),
                  const SizedBox(height: 2),
                  Text(hint, style: labelOf(context)),
                  if (error != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(error!, style: const TextStyle(color: Colors.red, fontSize: 13, fontWeight: FontWeight.w600))),
                  if (bytes != null) Padding(padding: const EdgeInsets.only(top: 4), child: Text(tr('Tap to retake'), style: const TextStyle(color: brand, fontSize: 13, fontWeight: FontWeight.w700))),
                ]),
              ),
            ]),
          ),
        ),
      );
}

/// Rider sign-up in three steps: your details and bike, your photos, check and send.
class ApplyScreen extends StatefulWidget {
  const ApplyScreen({super.key});
  @override
  State<ApplyScreen> createState() => _ApplyScreenState();
}

class _ApplyScreenState extends State<ApplyScreen> {
  int _step = 1;
  bool _busy = false, _consent = false, _hide = true;
  String? _formError;
  Map<String, String> _errors = {};
  final _c = {for (final k in ['name', 'national_id', 'phone', 'residence_area', 'bike_plate', 'bike_description', 'next_of_kin', 'next_of_kin_phone', 'password']) k: TextEditingController()};
  final _photos = <String, Uint8List>{};

  Applicant get _a => Applicant()
    ..name = _c['name']!.text
    ..nationalId = _c['national_id']!.text
    ..phone = _c['phone']!.text
    ..residence = _c['residence_area']!.text
    ..bikePlate = _c['bike_plate']!.text
    ..bikeDescription = _c['bike_description']!.text
    ..kin = _c['next_of_kin']!.text
    ..kinPhone = _c['next_of_kin_phone']!.text
    ..password = _c['password']!.text;

  static const _required = {
    'id_front': ('ID front', 'The side with your photo. All four corners in view, no glare.', Icons.badge_outlined),
    'id_back': ('ID back', 'The back of the same ID.', Icons.badge_outlined),
    'selfie': ('Selfie', 'Your face, clear and well lit. Customers see a small copy.', Icons.face_outlined),
  };

  void _next() {
    if (_step == 1) {
      final e = checkApplicant(_a);
      setState(() => _errors = e);
      if (e.isEmpty) setState(() => _step = 2);
    } else if (_step == 2) {
      final e = <String, String>{
        for (final k in _required.keys)
          if (!_photos.containsKey(k)) k: tr('Add this photo to continue.'),
      };
      setState(() => _errors = e);
      if (e.isEmpty) setState(() => _step = 3);
    }
  }

  Future<void> _submit() async {
    if (!_consent) {
      setState(() => _formError = tr('Tick the box to agree to the ID check.'));
      return;
    }
    setState(() {
      _busy = true;
      _formError = null;
    });
    final a = _a;
    try {
      await context.read<RiderSession>().apply(
        {
          'name': a.name.trim(),
          'phone': kenyanNumber(a.phone)!,
          'password': a.password,
          'national_id': a.nationalId.trim(),
          'next_of_kin': a.kin.trim(),
          'next_of_kin_phone': kenyanNumber(a.kinPhone)!,
          'residence_area': a.residence.trim(),
          'bike_plate': tidyPlate(a.bikePlate),
          'bike_description': a.bikeDescription.trim(),
          'consent': 'true',
        },
        {for (final e in _photos.entries) e.key: e.value},
      );
      if (mounted) Navigator.of(context).popUntil((r) => r.isFirst);
    } on ApiError catch (e) {
      if (!mounted) return;
      final errs = <String, String>{};
      final field = e.extra['field'];
      if (field is String) errs[field] = e.message;
      for (final f in (e.extra['fields'] as List? ?? const [])) {
        final loc = (f['loc'] as List?)?.last;
        if (loc is String) errs[loc] = '${f['msg'] ?? e.message}'.replaceFirst('Value error, ', '');
      }
      setState(() {
        _errors = errs;
        _formError = errs.isEmpty ? e.message : null;
        if (errs.isNotEmpty) _step = errs.keys.map(stepOfField).reduce((a, b) => a < b ? a : b);
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _field(String key, String label, {String? hint, TextInputType? type, bool password = false, int? max, TextCapitalization caps = TextCapitalization.none}) => Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: TextField(
          controller: _c[key],
          keyboardType: type,
          obscureText: password && _hide,
          maxLength: max,
          textCapitalization: caps,
          onChanged: (_) => _errors.containsKey(key) ? setState(() => _errors = {..._errors}..remove(key)) : null,
          decoration: InputDecoration(
            labelText: label,
            hintText: hint,
            counterText: '',
            errorText: _errors[key] == null ? null : tr(_errors[key]!),
            errorMaxLines: 3,
            suffixIcon: password ? IconButton(icon: Icon(_hide ? Icons.visibility_off_outlined : Icons.visibility_outlined), onPressed: () => setState(() => _hide = !_hide)) : null,
          ),
        ),
      );

  Widget _group(String title, List<Widget> children) => Container(
        margin: const EdgeInsets.only(bottom: 16),
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 0),
        decoration: BoxDecoration(border: Border.all(color: Theme.of(context).colorScheme.outlineVariant), borderRadius: BorderRadius.circular(18)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: kSection), const SizedBox(height: 12), ...children]),
      );

  Future<void> _pick(String kind) async {
    final b = await pickPhoto(context, selfie: kind == 'selfie');
    if (b != null && mounted) {
      setState(() {
        _photos[kind] = b;
        _errors = {..._errors}..remove(kind);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final titles = [tr('Your details'), tr('Photos'), tr('Check and send')];
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Apply to ride'), style: kSection),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(4),
          child: TweenAnimationBuilder<double>(
            tween: Tween(end: _step / 3),
            duration: const Duration(milliseconds: 300),
            builder: (_, v, __) => LinearProgressIndicator(value: v, minHeight: 4),
          ),
        ),
      ),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Text(tr('Step {n} of {total}', {'n': _step, 'total': 3}) + ' · ${titles[_step - 1]}', style: labelOf(context)),
        const SizedBox(height: 12),
        if (_formError != null) Container(width: double.infinity, margin: const EdgeInsets.only(bottom: 12), padding: const EdgeInsets.all(12), decoration: BoxDecoration(color: const Color(0xFFFEE2E2), borderRadius: BorderRadius.circular(12)), child: Text(_formError!, style: const TextStyle(color: Color(0xFFB91C1C), fontWeight: FontWeight.w700))),
        if (_step == 1) ...[
          _field('name', tr('Full name (as on your ID)'), hint: 'Wafula Simiyu Barasa', caps: TextCapitalization.words),
          _field('national_id', tr('ID number'), type: TextInputType.number, max: 9, hint: '30123456'),
          _field('phone', tr('Your phone (M-Pesa)'), type: TextInputType.phone, hint: '0712 345 678'),
          _field('residence_area', tr('Where you live'), hint: tr('Estate or area, e.g. Kanduyi near the stage')),
          _group(tr('Your bike'), [
            _field('bike_plate', tr('Number plate'), hint: 'KMFB 123C', max: 12, caps: TextCapitalization.characters),
            _field('bike_description', tr('Describe the bike'), hint: tr('Red Boxer 150 with a black box'), max: 200),
          ]),
          _group(tr('Next of kin'), [
            _field('next_of_kin', tr('Their full name'), caps: TextCapitalization.words),
            _field('next_of_kin_phone', tr('Their phone'), type: TextInputType.phone, hint: '0712 345 678'),
          ]),
          _field('password', tr('Choose a password'), password: true, hint: tr('At least 8 characters')),
        ],
        if (_step == 2) ...[
          for (final e in _required.entries)
            Padding(padding: const EdgeInsets.only(bottom: 10), child: PhotoSlot(title: tr(e.value.$1), hint: tr(e.value.$2), icon: e.value.$3, bytes: _photos[e.key], error: _errors[e.key], onTap: () => _pick(e.key))),
          PhotoSlot(title: tr('Bike logbook (optional)'), hint: tr("A clear photo of the bike's logbook. You can skip this, but it helps us approve you faster."), icon: Icons.description_outlined, bytes: _photos['logbook'], error: _errors['logbook'], onTap: () => _pick('logbook')),
        ],
        if (_step == 3) ...[
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(children: [
                _row(tr('Full name'), _c['name']!.text.trim()),
                _row(tr('ID number'), _c['national_id']!.text.trim()),
                _row(tr('Phone (M-Pesa)'), _c['phone']!.text.trim()),
                _row(tr('Lives in'), _c['residence_area']!.text.trim()),
                _row(tr('Bike'), '${tidyPlate(_c['bike_plate']!.text)} · ${_c['bike_description']!.text.trim()}'),
                _row(tr('Next of kin'), '${_c['next_of_kin']!.text.trim()} · ${_c['next_of_kin_phone']!.text.trim()}'),
              ]),
            ),
          ),
          const SizedBox(height: 12),
          Row(children: [
            for (final k in ['id_front', 'id_back', 'selfie', 'logbook'])
              if (_photos[k] != null) Expanded(child: Padding(padding: const EdgeInsets.only(right: 6), child: ClipRRect(borderRadius: BorderRadius.circular(10), child: AspectRatio(aspectRatio: 1, child: Image.memory(_photos[k]!, fit: BoxFit.cover))))),
          ]),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            value: _consent,
            onChanged: (v) => setState(() => _consent = v ?? false),
            title: Text(tr('I agree that Chakula keeps my ID photos, selfie and bike details to confirm who I am and to keep customers safe. Only the Chakula team can see them.'), style: kBody),
          ),
          Text(tr('Your ID is seen only by the Chakula team, never by hotels or customers.'), style: labelOf(context)),
        ],
        const SizedBox(height: 20),
        Row(children: [
          if (_step > 1) Expanded(child: OutlinedButton(onPressed: _busy ? null : () => setState(() => _step--), child: Text(tr('Back')))),
          if (_step > 1) const SizedBox(width: 12),
          Expanded(
            flex: 2,
            child: FilledButton(
              onPressed: _busy ? null : (_step == 3 ? _submit : _next),
              child: _busy
                  ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : Text(_step == 3 ? tr('Submit application') : tr('Continue')),
            ),
          ),
        ]),
        const SizedBox(height: 24),
      ]),
    );
  }

  Widget _row(String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 110, child: Text(k, style: labelOf(context))),
          Expanded(child: Text(v, style: kItem)),
        ]),
      );
}
