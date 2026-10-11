import 'scene.dart';
import 'scheme_view.dart';

/// Открытая схема (таб): своя сессия в бэкенде, своя камера и выделение.
class Doc {
  final int id; // номер документа в бэкенде
  Scene? scene;
  String? path; // открытый файл: картинка или .stj
  bool dirty = false; // есть несохранённые изменения (по данным бэкенда)
  Hit? selected;
  String? name; // имя, заданное пользователем (для ещё не сохранённой схемы)
  bool layersStale = false; // слои меняли, пока таб был неактивен
  final cam = SchemeController();
  Doc(this.id);

  Map<String, dynamic>? get source => scene?.source;
  String? get project => source?['project'] as String?;
}
