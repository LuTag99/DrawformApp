import 'package:flutter/cupertino.dart';

import '../services/python_service.dart';
import '../widgets/labeled_cupertino_field.dart';
import '../widgets/section_header.dart';

/// Page that allows exporting models into vector file formats.
class ExportPage extends StatefulWidget {
  const ExportPage({super.key});

  @override
  State<ExportPage> createState() => _ExportPageState();
}

class _ExportPageState extends State<ExportPage> {
  final TextEditingController _inputController = TextEditingController();
  String _format = 'dxf';
  String? _result;
  bool _loading = false;

  @override
  void dispose() {
    _inputController.dispose();
    super.dispose();
  }

  Future<void> _onExport() async {
    final input = _inputController.text.trim();
    if (input.isEmpty) {
      setState(() => _result = 'Bitte geben Sie einen Eingabepfad ein.');
      return;
    }
    setState(() {
      _loading = true;
      _result = null;
    });
    try {
      final outputPath =
          await PythonService.instance.exportToVector(input, _format);
      setState(() {
        _result = 'Export erfolgreich: $outputPath';
      });
    } catch (e) {
      setState(() {
        _result = 'Fehler beim Exportieren: $e';
      });
    } finally {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = CupertinoTheme.of(context);
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: CupertinoColors.systemGroupedBackground,
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionHeader(
              title: 'Export',
              subtitle: 'Wandle Modelle in Vektorformate um',
            ),
            LabeledCupertinoField(
              label: 'Pfad zum Eingabe‑3D‑Modell',
              controller: _inputController,
              keyboardType: TextInputType.text,
            ),
            const SizedBox(height: 20),
            Text(
              'Zielformat',
              style: theme.textTheme.textStyle,
            ),
            const SizedBox(height: 8),
            CupertinoSlidingSegmentedControl<String>(
              groupValue: _format,
              children: const {
                'dxf': Text('DXF'),
                'dwg': Text('DWG'),
                'svg': Text('SVG'),
                'pdf': Text('PDF'),
              },
              onValueChanged: (value) {
                if (value != null) {
                  setState(() => _format = value);
                }
              },
            ),
            const SizedBox(height: 24),
            CupertinoButton.filled(
              onPressed: _loading ? null : _onExport,
              child: _loading
                  ? const CupertinoActivityIndicator()
                  : const Text('Exportieren'),
            ),
            const SizedBox(height: 16),
            if (_result != null)
              Text(
                _result!,
                style: theme.textTheme.textStyle.copyWith(
                  color: _result!.startsWith('Fehler')
                      ? CupertinoColors.destructiveRed
                      : CupertinoColors.activeGreen,
                ),
              ),
          ],
        ),
      ),
    );
  }
}
