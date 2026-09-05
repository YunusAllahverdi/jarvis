// Weather — Open-Meteo via backend; iOS-style hero + 7-day strip.
import React, { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PanelShell, ErrorNote, LoadingBlock, Input, Btn } from "./_shell";
import { Sun, Cloud, CloudRain, CloudSnow, CloudFog, CloudLightning, CloudSun, Wind, Droplets, Search } from "lucide-react";

function icon(code, size = 20) {
  if (code === 0) return <Sun size={size} color="#ff9f0a" />;
  if (code <= 2) return <CloudSun size={size} color="#ff9f0a" />;
  if (code === 3) return <Cloud size={size} color="#8e8e93" />;
  if (code <= 48) return <CloudFog size={size} color="#8e8e93" />;
  if (code <= 67 || (code >= 80 && code <= 82)) return <CloudRain size={size} color="#32ade6" />;
  if (code <= 77) return <CloudSnow size={size} color="#64d2ff" />;
  return <CloudLightning size={size} color="#af52de" />;
}

export default function WeatherPanel() {
  const [city, setCity] = useState("İstanbul");
  const [q, setQ] = useState("İstanbul");
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setData(null); setErr(null);
    api.weather(city).then(setData).catch(setErr);
  }, [city]);

  return (
    <PanelShell
      title="Hava Durumu"
      subtitle="Open-Meteo verisi · 7 günlük tahmin"
      testId="weather-panel"
      right={
        <div className="flex items-center gap-2 w-64">
          <Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setCity(q.trim() || "İstanbul")} placeholder="Şehir…" data-testid="weather-city" />
          <Btn onClick={() => setCity(q.trim() || "İstanbul")} data-testid="weather-search"><Search size={12} /></Btn>
        </div>
      }
    >
      {err && <ErrorNote err={err} testId="weather-error" />}
      {!data && !err && <LoadingBlock />}
      {data && (
        <div className="p-6 max-w-3xl">
          <div className="rounded-3xl p-8 text-white relative overflow-hidden" style={{ background: "linear-gradient(160deg, #3d7bd9 0%, #5fa5ea 60%, #8fc6f0 100%)" }} data-testid="weather-hero">
            <p className="text-sm opacity-90">{data.city}{data.country ? `, ${data.country}` : ""}</p>
            <div className="flex items-end gap-4 mt-1">
              <p className="font-display text-7xl font-light leading-none">{Math.round(data.current.temp)}°</p>
              <div className="pb-2">{icon(data.current.code, 40)}</div>
            </div>
            <p className="text-base mt-2 opacity-95">{data.current.label}</p>
            <div className="flex gap-5 mt-4 text-sm opacity-90">
              <span className="flex items-center gap-1"><Droplets size={14} /> {data.current.humidity}%</span>
              <span className="flex items-center gap-1"><Wind size={14} /> {Math.round(data.current.wind)} km/s</span>
              <span>Hissedilen {Math.round(data.current.feels)}°</span>
            </div>
          </div>
          <div className="mt-4 glass-soft rounded-2xl divide-y divide-black/5">
            {data.daily.map((d, i) => (
              <div key={d.date} className="flex items-center gap-4 px-5 py-3" data-testid={`weather-day-${i}`}>
                <span className="w-24 text-sm font-medium">{i === 0 ? "Bugün" : new Date(d.date).toLocaleDateString("tr-TR", { weekday: "long" })}</span>
                {icon(d.code, 18)}
                <span className="flex-1 text-xs text-muted">{d.label}</span>
                <span className="text-sm text-muted w-10 text-right">{Math.round(d.min)}°</span>
                <span className="w-24 h-1.5 rounded-full bg-black/5 relative overflow-hidden">
                  <span className="absolute inset-y-0 rounded-full" style={{ left: `${Math.max(0, (d.min + 10) / 50) * 100}%`, right: `${Math.max(0, 1 - (d.max + 10) / 50) * 100}%`, background: "linear-gradient(90deg,#64d2ff,#ff9f0a)" }} />
                </span>
                <span className="text-sm font-semibold w-10 text-right">{Math.round(d.max)}°</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </PanelShell>
  );
}
