import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hotel_app/rider/screens/wallet.dart';

void main() {
  Map<String, dynamic> data(List<Map<String, dynamic>> activity) => {
        'enabled': true,
        'practice': true,
        'available': 470,
        'pending': 0,
        'paid': 1350,
        'min_payout': 50,
        'payout_time': '9:30 pm',
        'mpesa_last4': '0001',
        'can_withdraw': false,
        'activity': activity,
      };

  testWidgets('wallet shows balance, practice note and money in', (tester) async {
    tester.view.physicalSize = const Size(900, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final now = DateTime.now().toUtc().toIso8601String();
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: WalletTab(initial: data([{'id': '1', 'amount': 150, 'code': 'KR4T', 'hotel': 'Mama Rosy', 'at': now}]))),
    ));
    expect(find.text('KES 470'), findsOneWidget);
    expect(find.textContaining('Practice mode'), findsOneWidget);
    expect(find.text('Mama Rosy'), findsOneWidget);
    expect(find.text('+KES 150'), findsOneWidget);
    expect(find.text('Today'), findsOneWidget);
  });

  testWidgets('wallet with no activity says so', (tester) async {
    tester.view.physicalSize = const Size(900, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: WalletTab(initial: data([])))));
    expect(find.textContaining('Nothing yet'), findsOneWidget);
  });
}
