#ifndef RUNNER_SINGLE_INSTANCE_H_
#define RUNNER_SINGLE_INSTANCE_H_

#include <windows.h>

#include <string>

// Одна копия программы: повторный запуск (например, двойной щелчок по .stj)
// передаёт путь к файлу уже открытому окну и завершается.

// Метка главного окна (свойство окна) – по ней второй экземпляр находит первый.
constexpr const wchar_t kMainWindowProp[] = L"StationJoints.MainWindow";
// Тип сообщения WM_COPYDATA: «открыть файл».
constexpr ULONG_PTR kCopyDataOpen = 0x534A3031;  // 'SJ01'

// true – программа уже запущена, путь передан ей (этот экземпляр надо закрыть).
bool ForwardToRunningInstance(const std::wstring& path);

// Путь к файлу из командной строки (первый аргумент) или пустая строка.
std::wstring FirstArgument();

#endif  // RUNNER_SINGLE_INSTANCE_H_
