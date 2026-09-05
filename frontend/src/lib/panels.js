// Shared panel registry — used by Cowork window, Dock and command palette.
import {
  StickyNote, ShieldCheck, Users, Cpu, Database, Code2, History, Activity, Terminal as TermIcon, Calculator as CalcIcon,
  CalendarDays, ListChecks, Clock3, CloudSun, Languages,
} from "lucide-react";
import NotesPanel from "@/panels/NotesPanel";
import ApprovalsPanel from "@/panels/ApprovalsPanel";
import CouncilPanel from "@/panels/CouncilPanel";
import ProviderPanel from "@/panels/ProviderPanel";
import MemoryPanel from "@/panels/MemoryPanel";
import CodingPanel from "@/panels/CodingPanel";
import CheckpointsPanel from "@/panels/CheckpointsPanel";
import DiagnosticsPanel from "@/panels/DiagnosticsPanel";
import TerminalPanel from "@/panels/TerminalPanel";
import CalculatorPanel from "@/panels/CalculatorPanel";
import CalendarPanel from "@/panels/CalendarPanel";
import RemindersPanel from "@/panels/RemindersPanel";
import ClockPanel from "@/panels/ClockPanel";
import WeatherPanel from "@/panels/WeatherPanel";
import TranslatePanel from "@/panels/TranslatePanel";

export const PANELS = {
  notes:       { title: "Notlar",          icon: StickyNote,   comp: NotesPanel,       color: "#f5b400" },
  calendar:    { title: "Takvim",          icon: CalendarDays, comp: CalendarPanel,    color: "#ff3b30" },
  reminders:   { title: "Hatırlatıcılar",  icon: ListChecks,   comp: RemindersPanel,   color: "#ff9500" },
  weather:     { title: "Hava Durumu",     icon: CloudSun,     comp: WeatherPanel,     color: "#32ade6" },
  clock:       { title: "Saat",            icon: Clock3,       comp: ClockPanel,       color: "#1c1c1e" },
  translate:   { title: "Çeviri",          icon: Languages,    comp: TranslatePanel,   color: "#007aff" },
  approvals:   { title: "Onaylar",         icon: ShieldCheck,  comp: ApprovalsPanel,   color: "#34c759" },
  council:     { title: "Council",         icon: Users,        comp: CouncilPanel,     color: "#af52de" },
  memory:      { title: "Bellek",          icon: Database,     comp: MemoryPanel,      color: "#ff9f0a" },
  coding:      { title: "Kod Stüdyosu",    icon: Code2,        comp: CodingPanel,      color: "#0a84ff" },
  checkpoints: { title: "Checkpoint",      icon: History,      comp: CheckpointsPanel, color: "#64d2ff" },
  diagnostics: { title: "Tanılama",        icon: Activity,     comp: DiagnosticsPanel, color: "#ff375f" },
  terminal:    { title: "Terminal",        icon: TermIcon,     comp: TerminalPanel,    color: "#3a3a3c" },
  calculator:  { title: "Hesap Makinesi",  icon: CalcIcon,     comp: CalculatorPanel,  color: "#8e8e93" },
  provider:    { title: "Ayarlar",         icon: Cpu,          comp: ProviderPanel,    color: "#5e5ce6" },
};

export const DEFAULT_TABS = ["notes", "calendar", "reminders"];
