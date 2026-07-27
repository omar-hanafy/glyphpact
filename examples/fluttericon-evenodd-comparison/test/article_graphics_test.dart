import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:glyphpact_comparison/generated/fluttericon/flutter_icon_icons.dart';
import 'package:glyphpact_comparison/generated/glyphpact/glyph_pact_icons.dart';

const _background = Color(0xFF080B0F);
const _surface = Color(0xFF0E1319);
const _line = Color(0xFF242B34);
const _text = Color(0xFFF4F7FB);
const _muted = Color(0xFF9BA7B7);
const _subtle = Color(0xFF768296);
const _red = Color(0xFFFF817C);
const _green = Color(0xFF4BE18B);
const _cyan = Color(0xFF25C8E8);

const _cases = <_ArticleIconCase>[
  _ArticleIconCase(
    name: 'Location Bold',
    sourceAsset: 'assets/source_svg/Location Bold.svg',
    flutterIcon: FlutterIcon.location_bold,
    glyphPactIcon: GlyphPactIcons.locationBold,
    defect: 'Hole lost',
  ),
  _ArticleIconCase(
    name: 'Chat Bold',
    sourceAsset: 'assets/source_svg/Chat Bold.svg',
    flutterIcon: FlutterIcon.chat_bold,
    glyphPactIcon: GlyphPactIcons.chatBold,
    defect: 'Dot lost',
  ),
  _ArticleIconCase(
    name: 'Mail Bold',
    sourceAsset: 'assets/source_svg/Mail Bold.svg',
    flutterIcon: FlutterIcon.mail_bold,
    glyphPactIcon: GlyphPactIcons.mailBold,
    defect: 'Cutout lost',
  ),
];

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() async {
    await Future.wait([
      _loadFont('Geist', 'assets/fonts/Geist-Regular.ttf'),
      _loadFont('FlutterIcon', 'assets/fluttericon/fonts/FlutterIcon.ttf'),
      _loadFont(
        'GlyphPactIcons',
        'lib/generated/glyphpact/fonts/GlyphPactIcons.otf',
      ),
    ]);
  });

  testWidgets('renders the DEV comparison graphic', (tester) async {
    tester.view.physicalSize = const Size(1600, 1280);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      const _GraphicHost(
        child: _ScaledCanvas(
          key: ValueKey('comparison-canvas'),
          logicalSize: Size(800, 640),
          child: _ComparisonGraphic(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await expectLater(
      find.byKey(const ValueKey('comparison-canvas')),
      matchesGoldenFile('goldens/glyphpact-dev-comparison-v3-2x.png'),
    );
  });

  testWidgets('renders the DEV cover graphic', (tester) async {
    tester.view.physicalSize = const Size(2000, 840);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      const _GraphicHost(
        child: _ScaledCanvas(
          key: ValueKey('cover-canvas'),
          logicalSize: Size(1000, 420),
          child: _CoverGraphic(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await expectLater(
      find.byKey(const ValueKey('cover-canvas')),
      matchesGoldenFile('goldens/glyphpact-dev-cover-2x.png'),
    );
  });
}

Future<void> _loadFont(String family, String asset) async {
  final loader = FontLoader(family)..addFont(rootBundle.load(asset));
  await loader.load();
}

class _GraphicHost extends StatelessWidget {
  const _GraphicHost({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        fontFamily: 'Geist',
        scaffoldBackgroundColor: _background,
      ),
      home: Material(color: _background, child: child),
    );
  }
}

class _ScaledCanvas extends StatelessWidget {
  const _ScaledCanvas({
    required super.key,
    required this.logicalSize,
    required this.child,
  });

  final Size logicalSize;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return SizedBox.expand(
      child: FittedBox(
        fit: BoxFit.fill,
        child: SizedBox.fromSize(size: logicalSize, child: child),
      ),
    );
  }
}

class _ComparisonGraphic extends StatelessWidget {
  const _ComparisonGraphic();

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: RadialGradient(
          center: Alignment(0.92, -0.95),
          radius: 1.25,
          colors: [Color(0xFF13231C), _background],
          stops: [0, 0.65],
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(28, 24, 28, 20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const _ResultHeaders(),
            const SizedBox(height: 4),
            for (final iconCase in _cases)
              Expanded(child: _ArticleComparisonRow(iconCase: iconCase)),
            const SizedBox(height: 12),
            const _CompactFooter(),
          ],
        ),
      ),
    );
  }
}

class _ResultHeaders extends StatelessWidget {
  const _ResultHeaders();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(0, 2, 0, 15),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: _line)),
      ),
      child: const Row(
        children: [
          Expanded(
            child: _LargeHeader(
              title: 'ORIGINAL SVG',
              subtitle: 'Expected geometry',
              color: _text,
            ),
          ),
          SizedBox(width: 12),
          Expanded(
            child: _LargeHeader(
              title: 'FLUTTERICON.COM',
              subtitle: 'Generated TTF',
              color: _red,
            ),
          ),
          SizedBox(width: 12),
          Expanded(
            child: _LargeHeader(
              title: 'GLYPHPACT',
              subtitle: 'Generated OTF/CFF',
              color: _green,
            ),
          ),
        ],
      ),
    );
  }
}

class _LargeHeader extends StatelessWidget {
  const _LargeHeader({
    required this.title,
    required this.subtitle,
    required this.color,
  });

  final String title;
  final String subtitle;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            maxLines: 1,
            style: TextStyle(
              color: color,
              fontSize: 26,
              height: 1,
              fontWeight: FontWeight.w600,
              letterSpacing: -0.3,
            ),
          ),
          const SizedBox(height: 7),
          Text(
            subtitle,
            style: const TextStyle(
              color: _subtle,
              fontSize: 15,
              height: 1,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _ArticleComparisonRow extends StatelessWidget {
  const _ArticleComparisonRow({required this.iconCase});

  final _ArticleIconCase iconCase;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 11),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: _line)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Text(
                iconCase.name,
                style: const TextStyle(
                  color: _text,
                  fontSize: 22,
                  height: 1,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(width: 10),
              const Text(
                'fill-rule="evenodd"',
                style: TextStyle(
                  color: _subtle,
                  fontSize: 14,
                  height: 1,
                  fontFamily: 'Geist',
                  letterSpacing: 0.15,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Expanded(
            child: Row(
              children: [
                Expanded(
                  child: _ArticlePreviewCell(
                    label: 'Reference',
                    labelColor: _muted,
                    child: SvgPicture.asset(
                      iconCase.sourceAsset,
                      width: 72,
                      height: 72,
                      colorFilter: const ColorFilter.mode(
                        Color(0xFFF0F4F9),
                        BlendMode.srcIn,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _ArticlePreviewCell(
                    label: iconCase.defect,
                    labelColor: _red,
                    tint: const Color(0xFF1A1113),
                    child: Icon(iconCase.flutterIcon, size: 72, color: _red),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _ArticlePreviewCell(
                    label: 'Preserved',
                    labelColor: _green,
                    tint: const Color(0xFF0E1913),
                    child: Icon(
                      iconCase.glyphPactIcon,
                      size: 72,
                      color: _green,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ArticlePreviewCell extends StatelessWidget {
  const _ArticlePreviewCell({
    required this.label,
    required this.labelColor,
    required this.child,
    this.tint = _surface,
  });

  final String label;
  final Color labelColor;
  final Widget child;
  final Color tint;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: tint,
        border: Border.all(color: _line),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          SizedBox(width: 74, height: 74, child: Center(child: child)),
          const SizedBox(width: 8),
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                _StatusDot(color: labelColor, size: 7),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      color: labelColor,
                      fontSize: 20,
                      height: 1.08,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CompactFooter extends StatelessWidget {
  const _CompactFooter();

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        Text(
          'Actual Flutter render · same three source SVGs',
          style: TextStyle(
            color: _muted,
            fontSize: 15,
            fontWeight: FontWeight.w600,
          ),
        ),
        SizedBox(width: 12),
        Expanded(child: Divider(color: _line, height: 1)),
        SizedBox(width: 12),
        Text(
          '3 / 3 preserved',
          style: TextStyle(
            color: _green,
            fontSize: 16,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _CoverGraphic extends StatelessWidget {
  const _CoverGraphic();

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          colors: [Color(0xFF080B0F), Color(0xFF0C1813)],
          begin: Alignment.centerLeft,
          end: Alignment.centerRight,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(52, 42, 52, 38),
        child: Column(
          children: [
            const Row(
              children: [
                Expanded(
                  child: _CoverLabel(
                    title: 'FLUTTERICON.COM',
                    subtitle: 'Visible geometry lost',
                    color: _red,
                  ),
                ),
                SizedBox(width: 140),
                Expanded(
                  child: _CoverLabel(
                    title: 'GLYPHPACT',
                    subtitle: 'Geometry preserved',
                    color: _green,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 28),
            Expanded(
              child: Row(
                children: [
                  Expanded(
                    child: _CoverIconGroup(
                      color: _red,
                      background: const Color(0xFF1A1113),
                      icons: _cases.map((entry) => entry.flutterIcon).toList(),
                    ),
                  ),
                  const SizedBox(
                    width: 140,
                    child: Center(child: _CenterMark()),
                  ),
                  Expanded(
                    child: _CoverIconGroup(
                      color: _green,
                      background: const Color(0xFF0E1913),
                      icons: _cases
                          .map((entry) => entry.glyphPactIcon)
                          .toList(),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CoverLabel extends StatelessWidget {
  const _CoverLabel({
    required this.title,
    required this.subtitle,
    required this.color,
  });

  final String title;
  final String subtitle;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          title,
          style: TextStyle(
            color: color,
            fontSize: 18,
            height: 1,
            fontWeight: FontWeight.w600,
            letterSpacing: 1.2,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          subtitle,
          style: const TextStyle(
            color: _muted,
            fontSize: 14,
            height: 1,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _CoverIconGroup extends StatelessWidget {
  const _CoverIconGroup({
    required this.color,
    required this.background,
    required this.icons,
  });

  final Color color;
  final Color background;
  final List<IconData> icons;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: background,
        border: Border.all(color: color.withValues(alpha: 0.3)),
        borderRadius: BorderRadius.circular(22),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          for (final icon in icons) Icon(icon, size: 92, color: color),
        ],
      ),
    );
  }
}

class _CenterMark extends StatelessWidget {
  const _CenterMark();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Expanded(child: Divider(color: Color(0xFF1B778A), height: 1)),
        const SizedBox(width: 12),
        Transform.rotate(
          angle: 0.785398,
          child: Container(
            width: 22,
            height: 22,
            decoration: const BoxDecoration(
              color: _cyan,
              boxShadow: [BoxShadow(color: Color(0x5525C8E8), blurRadius: 18)],
            ),
          ),
        ),
        const SizedBox(width: 12),
        const Expanded(child: Divider(color: Color(0xFF1B778A), height: 1)),
      ],
    );
  }
}

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.color, required this.size});

  final Color color;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
        boxShadow: [
          BoxShadow(color: color.withValues(alpha: 0.32), blurRadius: 6),
        ],
      ),
    );
  }
}

class _ArticleIconCase {
  const _ArticleIconCase({
    required this.name,
    required this.sourceAsset,
    required this.flutterIcon,
    required this.glyphPactIcon,
    required this.defect,
  });

  final String name;
  final String sourceAsset;
  final IconData flutterIcon;
  final IconData glyphPactIcon;
  final String defect;
}
