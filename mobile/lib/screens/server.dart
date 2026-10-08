import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../api.dart';
import '../i18n.dart';
import '../util.dart';

/// Change which server the app talks to, with a connection test. Returns true if the address changed.
Future<bool> showServerDialog(BuildContext context) async {
  final field = TextEditingController(text: apiBase.replaceFirst(RegExp(r'/api/v1$'), ''));
  String? result;
  Color resultColor = kMuted;
  var busy = false;
  final changed = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) => AlertDialog(
        title: Text(tr('Server address')),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tr("The address of the Chakula server, for example 10.10.35.108:8000. Your PC's Wi-Fi address can change, so check it if the app can't connect."), style: const TextStyle(fontSize: 13)),
          const SizedBox(height: 12),
          TextField(controller: field, keyboardType: TextInputType.url, autocorrect: false, decoration: const InputDecoration(hintText: '10.10.35.108:8000')),
          if (result != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(result!, style: TextStyle(color: resultColor, fontWeight: FontWeight.w700, fontSize: 13))),
        ]),
        actions: [
          TextButton(
            onPressed: busy
                ? null
                : () async {
                    await saveServerSetting(null);
                    if (ctx.mounted) Navigator.pop(ctx, true);
                  },
            child: Text(tr('Reset')),
          ),
          TextButton(
            onPressed: busy
                ? null
                : () async {
                    final n = normaliseServer(field.text);
                    if (n == null) {
                      set(() {
                        result = tr("That doesn't look like an address");
                        resultColor = Colors.red;
                      });
                      return;
                    }
                    set(() {
                      busy = true;
                      result = tr('Testing…');
                      resultColor = kMuted;
                    });
                    try {
                      final r = await http.get(Uri.parse('$n/config')).timeout(const Duration(seconds: 8));
                      set(() {
                        result = r.statusCode == 200 ? tr('Connected') : tr('Reached a server, but it did not answer as Chakula ({code})', {'code': r.statusCode});
                        resultColor = r.statusCode == 200 ? const Color(0xFF15803D) : Colors.red;
                      });
                    } catch (_) {
                      set(() {
                        result = tr("Can't reach that address. Check the address and that the PC and phone are on the same Wi-Fi.");
                        resultColor = Colors.red;
                      });
                    } finally {
                      set(() => busy = false);
                    }
                  },
            child: Text(tr('Test')),
          ),
          FilledButton(
            style: FilledButton.styleFrom(minimumSize: const Size(88, 44)),
            onPressed: busy
                ? null
                : () async {
                    final ok = await saveServerSetting(field.text);
                    if (!ok) {
                      set(() {
                        result = tr("That doesn't look like an address");
                        resultColor = Colors.red;
                      });
                      return;
                    }
                    if (ctx.mounted) Navigator.pop(ctx, true);
                  },
            child: Text(tr('Save')),
          ),
        ],
      ),
    ),
  );
  field.dispose();
  return changed == true;
}
