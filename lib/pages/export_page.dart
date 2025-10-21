import 'package:file_picker/file_picker.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../services/python_service.dart';
import '../theme/ai_theme.dart';
import '../widgets/ai_gradient_button.dart';
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

  Future<void> _pickFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: const ['stl', 'obj', 'step', 'iges'],
      );
      final path = result?.files.single.path;
      if (path != null) {
        setState(() {
          _inputController.text = path;
          _result = null;
        });
      }
    } catch (e) {
      setState(() {
        _result = 'Fehler beim Öffnen des Dateidialogs: $e';
      });
    }
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
    final brightness = Theme.of(context).brightness;
    final textTheme = CupertinoTheme.of(context).textTheme.textStyle;

    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SectionHeader(
            title: 'Export',
            subtitle: 'Wandle Modelle in Vektorformate um',
          ),
          const SizedBox(height: 12),
          DecoratedBox(
            decoration: AiTheme.glassSurface(
              brightness: brightness,
              borderRadius: AiTheme.largeRadius,
              opacity: 0.9,
            ),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  LabeledCupertinoField(
                    label: 'Pfad zum Eingabe-3D-Modell',
                    controller: _inputController,
                    keyboardType: TextInputType.text,
                    placeholder: 'C:/Projects/models/example.stl',
                    trailing: _UploadButton(
                      onPressed: _loading ? null : _pickFile,
                    ),
                  ),
                  const SizedBox(height: 20),
                  Text(
                    'Zielformat',
                    style: textTheme.copyWith(
                      fontWeight: FontWeight.w600,
                      letterSpacing: 0.2,
                    ),
                  ),
                  const SizedBox(height: 10),
                  CupertinoSlidingSegmentedControl<String>(
                    groupValue: _format,
                    backgroundColor: AiTheme.glassSurfaceColor
                        .resolveFrom(context)
                        .withValues(alpha: 0.35),
                    thumbColor: Theme.of(context)
                        .colorScheme
                        .secondary
                        .withValues(alpha: 0.85),
                    children: const {
                      'dxf': Padding(
                        padding:
                            EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        child: Text('DXF'),
                      ),
                      'dwg': Padding(
                        padding:
                            EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        child: Text('DWG'),
                      ),
                      'svg': Padding(
                        padding:
                            EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        child: Text('SVG'),
                      ),
                      'pdf': Padding(
                        padding:
                            EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                        child: Text('PDF'),
                      ),
                    },
                    onValueChanged: (value) {
                      if (value != null) {
                        setState(() => _format = value);
                      }
                    },
                  ),
                  const SizedBox(height: 24),
                  AiGradientButton(
                    label: 'Exportieren',
                    onPressed: _loading ? null : _onExport,
                    busy: _loading,
                  ),
                  const SizedBox(height: 20),
                  if (_result != null)
                    _ExportResultBanner(
                      message: _result!,
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _UploadButton extends StatelessWidget {
  const _UploadButton({required this.onPressed});

  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final bool enabled = onPressed != null;
    final brightness = Theme.of(context).brightness;

    return AnimatedOpacity(
      duration: const Duration(milliseconds: 180),
      opacity: enabled ? 1 : 0.6,
      child: CupertinoButton(
        padding: EdgeInsets.zero,
        onPressed: onPressed,
        borderRadius: AiTheme.mediumRadius,
        child: DecoratedBox(
          decoration: BoxDecoration(
            gradient: enabled
                ? AiTheme.accentGradient(brightness)
                : LinearGradient(
                    colors: [
                      Theme.of(context)
                          .colorScheme
                          .surface
                          .withValues(alpha: 0.45),
                      Theme.of(context)
                          .colorScheme
                          .surface
                          .withValues(alpha: 0.45),
                    ],
                  ),
            borderRadius: AiTheme.mediumRadius,
          ),
          child: const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  CupertinoIcons.arrow_down_doc,
                  size: 16,
                  color: Colors.white,
                ),
                SizedBox(width: 8),
                Text(
                  'Datei wählen',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ExportResultBanner extends StatelessWidget {
  const _ExportResultBanner({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final bool isError = message.startsWith('Fehler');
    final Color color =
        isError ? CupertinoColors.destructiveRed : CupertinoColors.activeGreen;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          Icon(
            isError
                ? CupertinoIcons.exclamationmark_triangle_fill
                : CupertinoIcons.check_mark_circled_solid,
            color: color,
            size: 18,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: TextStyle(
                color: color,
                fontSize: 13,
                height: 1.4,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
