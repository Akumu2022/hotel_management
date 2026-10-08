import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../store.dart';
import '../i18n.dart';
import '../util.dart';
import 'checkout.dart';
import 'home.dart';
import 'orders.dart';

/// Which bottom-nav tab is showing. Any screen can set it (e.g. "Home" buttons).
final tabIndex = ValueNotifier<int>(0);

/// Pops everything above the shell and shows the Home tab (the web's logo link).
void goHome(BuildContext context) {
  tabIndex.value = 0;
  Navigator.of(context).popUntil((r) => r.isFirst);
}

/// App frame: Home / Orders / Cart with a bottom navigation bar.
class Shell extends StatelessWidget {
  const Shell({super.key});

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<AppState>();
    return ValueListenableBuilder<int>(
      valueListenable: tabIndex,
      builder: (_, i, __) => Scaffold(
        // Home stays alive (keeps scroll and loaded data); Orders and Cart are rebuilt each time
        // they're opened so they always show fresh data.
        body: IndexedStack(index: i, children: [
          const HomeScreen(),
          i == 1 ? const OrdersScreen() : const SizedBox.shrink(),
          i == 2 ? const CheckoutScreen() : const SizedBox.shrink(),
        ]),
        bottomNavigationBar: NavigationBar(
          selectedIndex: i,
          backgroundColor: Colors.white,
          indicatorColor: const Color(0xFFFFE4D6),
          height: 66,
          onDestinationSelected: (v) => tabIndex.value = v,
          destinations: [
            NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home_rounded, color: brand), label: tr('Home')),
            NavigationDestination(icon: Icon(Icons.receipt_long_outlined), selectedIcon: Icon(Icons.receipt_long, color: brand), label: tr('Orders')),
            NavigationDestination(
              icon: Badge(isLabelVisible: cart.count > 0, label: Text('${cart.count}'), child: const Icon(Icons.shopping_basket_outlined)),
              selectedIcon: Badge(isLabelVisible: cart.count > 0, label: Text('${cart.count}'), child: const Icon(Icons.shopping_basket, color: brand)),
              label: tr('Cart'),
            ),
          ],
        ),
      ),
    );
  }
}
