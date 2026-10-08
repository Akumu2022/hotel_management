import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_app/api.dart';
import 'package:hotel_app/i18n.dart';
import 'package:hotel_app/store.dart';
import 'package:hotel_app/util.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  group('kes', () {
    test('formats whole shillings with thousands separators', () {
      expect(kes(0), 'KES 0');
      expect(kes(270), 'KES 270');
      expect(kes(1220), 'KES 1,220');
      expect(kes(1234567), 'KES 1,234,567');
    });
  });

  group('tr', () {
    tearDown(() => lang.value = 'en');

    test('English passes through and fills placeholders', () {
      expect(tr('Step {n} of {total}', {'n': 2, 'total': 7}), 'Step 2 of 7');
    });

    test('Kiswahili translates, fills placeholders and falls back to English', () {
      lang.value = 'sw';
      expect(tr('Hotels near you'), 'Hoteli zilizo karibu nawe');
      expect(tr('Step {n} of {total}', {'n': 2, 'total': 7}), 'Hatua 2 kati ya 7');
      expect(tr('A phrase nobody translated'), 'A phrase nobody translated');
    });
  });

  group('food emoji', () {
    test('picks a fitting emoji, with a plate as the default', () {
      expect(foodEmoji('PIZZA'), '🍕');
      expect(foodEmoji('Capucino Espresso'), '☕');
      expect(foodEmoji('Mystery dish'), '🍽️');
    });
  });

  group('AppState', () {
    late AppState s;
    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      s = AppState();
      await s.load();
    });

    test('order again refills the cart and the order type', () {
      s.orderAgain({
        'hotel_slug': 'noor-cafe',
        'hotel_name': 'Noor Cafe',
        'type': 'pickup',
        'items': [
          {'product_id': 'p1', 'option_ids': <String>[], 'name': 'PIZZA', 'options': <String>[], 'quantity': 2, 'line_total': 1800},
        ],
      });
      expect(s.hotelSlug, 'noor-cafe');
      expect(s.count, 2);
      expect(s.lines.single.unitPrice, 900);
      expect(s.mode, 'pickup');
    });

    test('the cart holds one hotel at a time', () {
      final line = CartLine('p1', [], 'PIZZA', '', 900, 1);
      expect(s.add('a', 'Hotel A', line), isTrue);
      expect(s.add('b', 'Hotel B', CartLine('p2', [], 'Tea', '', 50, 1)), isFalse);
    });

    test('an unfinished checkout is remembered across restarts so a retry reuses its key', () async {
      s.setPending({'sig': 'abc', 'key': 'key-1', 'arrive': null});
      final again = AppState();
      await again.load();
      expect(again.pending?['key'], 'key-1');
      again.setPending(null);
      final cleared = AppState();
      await cleared.load();
      expect(cleared.pending, isNull);
    });

    test('saved places replace the one with the same label', () {
      s.savePlace('Home', 0.5, 34.5, 'blue gate');
      s.savePlace('Home', 0.6, 34.6, 'green gate');
      expect(s.places.length, 1);
      expect(s.places.single['landmark'], 'green gate');
    });
  });

  group('server address setting', () {
    test('is tidied into a full API address', () {
      expect(normaliseServer('10.10.35.108:8000'), 'http://10.10.35.108:8000/api/v1');
      expect(normaliseServer('  http://pc.local:8000/ '), 'http://pc.local:8000/api/v1');
      expect(normaliseServer('https://chakula.co.ke'), 'https://chakula.co.ke/api/v1');
      expect(normaliseServer('http://10.0.2.2:8000/api/v1'), 'http://10.0.2.2:8000/api/v1');
    });

    test('rejects things that cannot be an address', () {
      expect(normaliseServer(''), isNull);
      expect(normaliseServer('   '), isNull);
      expect(normaliseServer('not an address'), isNull);
      expect(normaliseServer('ftp://x'), isNull);
    });

    test('is remembered on the phone and can be reset', () async {
      SharedPreferences.setMockInitialValues({});
      expect(await saveServerSetting('10.10.35.108:8000'), isTrue);
      expect(apiBase, 'http://10.10.35.108:8000/api/v1');
      apiBase = defaultApiBase; // a restart
      await loadServerSetting();
      expect(apiBase, 'http://10.10.35.108:8000/api/v1');
      expect(await saveServerSetting('???'), isFalse); // a bad address changes nothing
      expect(apiBase, 'http://10.10.35.108:8000/api/v1');
      expect(await saveServerSetting(''), isTrue);
      expect(apiBase, defaultApiBase);
    });
  });

  testWidgets('Pill shows its text', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Pill('Open now'))));
    expect(find.text('Open now'), findsOneWidget);
  });
}
