import 'package:flutter/material.dart';
import '../i18n.dart';
import '../util.dart';

/// Liquor is for people 18 and over: asked once, and the phone remembers.
class AgeGate extends StatelessWidget {
  final VoidCallback onYes, onNo;
  const AgeGate({super.key, required this.onYes, required this.onNo});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.shield_outlined, size: 48, color: brand),
          const SizedBox(height: 12),
          Text(tr('Are you 18 or older?'), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Text(
            tr('Alcohol is sold only to people aged 18 and over. The rider will check your ID at the door.'),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 20),
          SizedBox(width: double.infinity, child: FilledButton(onPressed: onYes, child: Text(tr('Yes, I am 18 or older')))),
          const SizedBox(height: 8),
          SizedBox(width: double.infinity, child: OutlinedButton(onPressed: onNo, child: Text(tr('No, go back')))),
        ]),
      );
}
