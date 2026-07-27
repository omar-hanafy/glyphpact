import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:glyphpact_comparison/generated/fluttericon/flutter_icon_icons.dart';
import 'package:glyphpact_comparison/generated/glyphpact/glyph_pact_icons.dart';

void main() {
  runApp(const GlyphPactComparisonApp());
}

class GlyphPactComparisonApp extends StatelessWidget {
  const GlyphPactComparisonApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'GlyphPact comparison',
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF080B0F),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF4BE18B),
          brightness: Brightness.dark,
        ),
        textTheme: ThemeData.dark().textTheme.apply(
          bodyColor: const Color(0xFFF4F7FB),
          displayColor: const Color(0xFFF4F7FB),
        ),
      ),
      home: const ComparisonPage(),
    );
  }
}

class ComparisonPage extends StatefulWidget {
  const ComparisonPage({super.key});

  @override
  State<ComparisonPage> createState() => _ComparisonPageState();
}

class _ComparisonPageState extends State<ComparisonPage>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;
  late final Animation<Offset> _offset;

  static const _cases = <_IconCase>[
    _IconCase(
      name: 'Location Bold',
      sourceAsset: 'assets/source_svg/Location Bold.svg',
      flutterIcon: FlutterIcon.location_bold,
      glyphPactIcon: GlyphPactIcons.locationBold,
      defect: 'Center hole lost',
    ),
    _IconCase(
      name: 'Chat Bold',
      sourceAsset: 'assets/source_svg/Chat Bold.svg',
      flutterIcon: FlutterIcon.chat_bold,
      glyphPactIcon: GlyphPactIcons.chatBold,
      defect: 'Third dot lost',
    ),
    _IconCase(
      name: 'Mail Bold',
      sourceAsset: 'assets/source_svg/Mail Bold.svg',
      flutterIcon: FlutterIcon.mail_bold,
      glyphPactIcon: GlyphPactIcons.mailBold,
      defect: 'Envelope cutout lost',
    ),
  ];

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 650),
    )..forward();
    _opacity = CurvedAnimation(
      parent: _controller,
      curve: const Interval(0, 0.8, curve: Curves.easeOut),
    );
    _offset = Tween<Offset>(
      begin: const Offset(0, 0.018),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic));
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: RadialGradient(
            center: Alignment(0.72, -0.86),
            radius: 1.1,
            colors: [Color(0xFF13231C), Color(0xFF080B0F)],
            stops: [0, 0.62],
          ),
        ),
        child: SafeArea(
          child: FadeTransition(
            opacity: _opacity,
            child: SlideTransition(
              position: _offset,
              child: LayoutBuilder(
                builder: (context, constraints) {
                  return SingleChildScrollView(
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: ConstrainedBox(
                        constraints: BoxConstraints(
                          minWidth: constraints.maxWidth < 1180
                              ? 1180
                              : constraints.maxWidth,
                        ),
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(54, 38, 54, 34),
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(maxWidth: 1480),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                const _Masthead(),
                                const SizedBox(height: 30),
                                const _ColumnHeader(),
                                ..._cases.map(_ComparisonRow.new),
                                const _BuildProof(),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Masthead extends StatelessWidget {
  const _Masthead();

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  SvgPicture.asset(
                    'assets/glyphpact-icon.svg',
                    width: 42,
                    height: 42,
                  ),
                  const SizedBox(width: 13),
                  const Text(
                    'GlyphPact',
                    style: TextStyle(
                      fontSize: 26,
                      height: 1,
                      fontWeight: FontWeight.w800,
                      letterSpacing: -0.7,
                    ),
                  ),
                  const SizedBox(width: 12),
                  const _Pill(
                    label: 'v1.0.1',
                    foreground: Color(0xFFAAB6C6),
                    background: Color(0xFF151B22),
                  ),
                ],
              ),
              const SizedBox(height: 25),
              const Text(
                'Same SVGs.\nDifferent result.',
                style: TextStyle(
                  fontSize: 48,
                  height: 0.98,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -2.2,
                ),
              ),
              const SizedBox(height: 14),
              const Text(
                'Three valid even-odd SVGs, rendered inside the same Flutter app.',
                style: TextStyle(
                  color: Color(0xFF9BA7B7),
                  fontSize: 17,
                  height: 1.45,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 48),
        const Padding(padding: EdgeInsets.only(top: 7), child: _ProofStamp()),
      ],
    );
  }
}

class _ProofStamp extends StatelessWidget {
  const _ProofStamp();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 284,
      padding: const EdgeInsets.fromLTRB(20, 17, 20, 18),
      decoration: BoxDecoration(
        color: const Color(0xFF0F1914),
        border: Border.all(color: const Color(0xFF275D42)),
        borderRadius: BorderRadius.circular(16),
      ),
      child: const Row(
        children: [
          _StatusDot(color: Color(0xFF4BE18B)),
          SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'STRICT BUILD',
                  style: TextStyle(
                    color: Color(0xFF4BE18B),
                    fontSize: 11,
                    height: 1,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.5,
                  ),
                ),
                SizedBox(height: 7),
                Text(
                  '3 lossless · 0 issues',
                  style: TextStyle(
                    fontSize: 16,
                    height: 1,
                    fontWeight: FontWeight.w700,
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

class _ColumnHeader extends StatelessWidget {
  const _ColumnHeader();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        border: Border(
          top: BorderSide(color: Color(0xFF242B34)),
          bottom: BorderSide(color: Color(0xFF242B34)),
        ),
      ),
      padding: const EdgeInsets.symmetric(vertical: 17),
      child: const Row(
        children: [
          Expanded(
            flex: 20,
            child: _HeaderLabel(title: 'ICON', subtitle: 'Exact source file'),
          ),
          Expanded(
            flex: 26,
            child: _HeaderLabel(
              title: 'ORIGINAL SVG',
              subtitle: 'Expected geometry',
            ),
          ),
          Expanded(
            flex: 27,
            child: _HeaderLabel(
              title: 'FLUTTERICON.COM',
              subtitle: 'Generated TTF',
              color: Color(0xFFFF817C),
            ),
          ),
          Expanded(
            flex: 27,
            child: _HeaderLabel(
              title: 'GLYPHPACT',
              subtitle: 'Generated OpenType',
              color: Color(0xFF4BE18B),
            ),
          ),
        ],
      ),
    );
  }
}

class _HeaderLabel extends StatelessWidget {
  const _HeaderLabel({
    required this.title,
    required this.subtitle,
    this.color = const Color(0xFF97A4B6),
  });

  final String title;
  final String subtitle;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              color: color,
              fontSize: 12,
              height: 1,
              fontWeight: FontWeight.w800,
              letterSpacing: 1.4,
            ),
          ),
          const SizedBox(height: 7),
          Text(
            subtitle,
            style: const TextStyle(
              color: Color(0xFF697485),
              fontSize: 12,
              height: 1,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

class _ComparisonRow extends StatefulWidget {
  const _ComparisonRow(this.iconCase);

  final _IconCase iconCase;

  @override
  State<_ComparisonRow> createState() => _ComparisonRowState();
}

class _ComparisonRowState extends State<_ComparisonRow> {
  var _hovered = false;

  @override
  Widget build(BuildContext context) {
    final iconCase = widget.iconCase;
    return MouseRegion(
      onEnter: (_) => setState(() => _hovered = true),
      onExit: (_) => setState(() => _hovered = false),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
        height: 164,
        decoration: BoxDecoration(
          color: _hovered ? const Color(0xFF10151B) : const Color(0x00000000),
          border: const Border(bottom: BorderSide(color: Color(0xFF242B34))),
        ),
        child: Row(
          children: [
            Expanded(
              flex: 20,
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 18),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      iconCase.name,
                      style: const TextStyle(
                        fontSize: 19,
                        height: 1,
                        fontWeight: FontWeight.w700,
                        letterSpacing: -0.35,
                      ),
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      'fill-rule="evenodd"',
                      style: TextStyle(
                        color: Color(0xFF778395),
                        fontSize: 12,
                        height: 1,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Expanded(
              flex: 26,
              child: _PreviewCell(
                label: 'Reference',
                labelColor: const Color(0xFF9BA7B7),
                child: SvgPicture.asset(
                  iconCase.sourceAsset,
                  width: 76,
                  height: 76,
                  colorFilter: const ColorFilter.mode(
                    Color(0xFFF0F4F9),
                    BlendMode.srcIn,
                  ),
                ),
              ),
            ),
            Expanded(
              flex: 27,
              child: _PreviewCell(
                label: iconCase.defect,
                labelColor: const Color(0xFFFF817C),
                tint: const Color(0xFF1A1113),
                child: Icon(
                  iconCase.flutterIcon,
                  size: 76,
                  color: const Color(0xFFFF817C),
                ),
              ),
            ),
            Expanded(
              flex: 27,
              child: _PreviewCell(
                label: 'Geometry preserved',
                labelColor: const Color(0xFF4BE18B),
                tint: const Color(0xFF0E1913),
                child: Icon(
                  iconCase.glyphPactIcon,
                  size: 76,
                  color: const Color(0xFF4BE18B),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PreviewCell extends StatelessWidget {
  const _PreviewCell({
    required this.label,
    required this.labelColor,
    required this.child,
    this.tint = const Color(0xFF0E1319),
  });

  final String label;
  final Color labelColor;
  final Widget child;
  final Color tint;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 18),
      child: Container(
        decoration: BoxDecoration(
          color: tint,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: const Color(0xFF222A33)),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 18),
        child: Row(
          children: [
            SizedBox(width: 84, height: 84, child: Center(child: child)),
            const SizedBox(width: 17),
            Expanded(
              child: Row(
                children: [
                  _StatusDot(color: labelColor, size: 7),
                  const SizedBox(width: 9),
                  Flexible(
                    child: Text(
                      label,
                      style: TextStyle(
                        color: labelColor,
                        fontSize: 13,
                        height: 1.2,
                        fontWeight: FontWeight.w700,
                      ),
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

class _BuildProof extends StatelessWidget {
  const _BuildProof();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 24),
      child: Row(
        children: [
          const Text(
            'Actual Flutter render',
            style: TextStyle(
              color: Color(0xFFA8B3C2),
              fontSize: 13,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(width: 14),
          const Expanded(child: Divider(color: Color(0xFF242B34), height: 1)),
          const SizedBox(width: 14),
          ...const [
            _ProofMetric(value: '3 / 3', label: 'lossless'),
            _ProofMetric(value: '0', label: 'approximated'),
            _ProofMetric(value: '0', label: 'skipped'),
            _ProofMetric(value: '0', label: 'issues'),
          ],
        ],
      ),
    );
  }
}

class _ProofMetric extends StatelessWidget {
  const _ProofMetric({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 28),
      child: Row(
        children: [
          Text(
            value,
            style: const TextStyle(
              color: Color(0xFF4BE18B),
              fontSize: 15,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(width: 7),
          Text(
            label,
            style: const TextStyle(
              color: Color(0xFF7D8999),
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({
    required this.label,
    required this.foreground,
    required this.background,
  });

  final String label;
  final Color foreground;
  final Color background;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFF29313B)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: foreground,
          fontSize: 11,
          height: 1,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.3,
        ),
      ),
    );
  }
}

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.color, this.size = 9});

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
          BoxShadow(color: color.withValues(alpha: 0.35), blurRadius: 7),
        ],
      ),
    );
  }
}

class _IconCase {
  const _IconCase({
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
