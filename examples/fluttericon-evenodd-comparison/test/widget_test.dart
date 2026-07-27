import 'dart:ui' show Size;

import 'package:flutter_test/flutter_test.dart';
import 'package:glyphpact_comparison/main.dart';

void main() {
  testWidgets('shows all three comparison rows', (tester) async {
    tester.view.physicalSize = const Size(1440, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(const GlyphPactComparisonApp());
    await tester.pumpAndSettle();

    expect(find.text('Location Bold'), findsOneWidget);
    expect(find.text('Chat Bold'), findsOneWidget);
    expect(find.text('Mail Bold'), findsOneWidget);
    expect(find.text('Center hole lost'), findsOneWidget);
    expect(find.text('3 lossless · 0 issues'), findsOneWidget);
  });
}
