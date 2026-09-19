#include "single_instance.h"

#include <shellapi.h>

namespace {

BOOL CALLBACK FindMain(HWND hwnd, LPARAM out) {
  if (::GetPropW(hwnd, kMainWindowProp)) {
    *reinterpret_cast<HWND*>(out) = hwnd;
    return FALSE;
  }
  return TRUE;
}

HWND FindMainWindow() {
  HWND found = nullptr;
  ::EnumWindows(FindMain, reinterpret_cast<LPARAM>(&found));
  return found;
}

}  // namespace

std::wstring FirstArgument() {
  int argc = 0;
  wchar_t** argv = ::CommandLineToArgvW(::GetCommandLineW(), &argc);
  std::wstring path;
  if (argv != nullptr) {
    if (argc > 1) path = argv[1];
    ::LocalFree(argv);
  }
  return path;
}

bool ForwardToRunningInstance(const std::wstring& path) {
  // мьютекс живёт, пока жив первый экземпляр (освобождается системой при выходе)
  ::CreateMutexW(nullptr, TRUE, L"Local\\StationJoints.SingleInstance");
  if (::GetLastError() != ERROR_ALREADY_EXISTS) return false;

  // первый экземпляр может ещё запускаться – ждём его окно до 5 с
  HWND main = nullptr;
  for (int i = 0; i < 50 && main == nullptr; ++i) {
    main = FindMainWindow();
    if (main == nullptr) ::Sleep(100);
  }
  if (main == nullptr) return false;  // окна нет – запускаемся как обычно

  if (!path.empty()) {
    COPYDATASTRUCT cds;
    cds.dwData = kCopyDataOpen;
    cds.cbData = static_cast<DWORD>((path.size() + 1) * sizeof(wchar_t));
    cds.lpData = const_cast<wchar_t*>(path.c_str());
    DWORD_PTR result = 0;
    ::SendMessageTimeoutW(main, WM_COPYDATA, 0, reinterpret_cast<LPARAM>(&cds),
                          SMTO_ABORTIFHUNG, 5000, &result);
  }
  // показать уже открытое окно (этот процесс запущен пользователем – ему можно)
  if (::IsIconic(main)) ::ShowWindow(main, SW_RESTORE);
  ::SetForegroundWindow(main);
  return true;
}
