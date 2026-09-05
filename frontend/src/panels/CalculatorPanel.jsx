// Local calculator — utility tool inside Cowork tabs.
import React, { useState } from "react";
import { PanelShell, Btn } from "./_shell";

const BTNS = [
  ["7","8","9","÷"],
  ["4","5","6","×"],
  ["1","2","3","−"],
  ["0",".","=","+"],
];

export default function CalculatorPanel() {
  const [expr, setExpr] = useState("");
  const [out, setOut] = useState("0");

  const norm = (s) => s.replace(/÷/g, "/").replace(/×/g, "*").replace(/−/g, "-");
  const push = (k) => {
    if (k === "=") {
      try {
        // eslint-disable-next-line no-new-func
        const v = Function(`"use strict"; return (${norm(expr) || "0"})`)();
        setOut(String(v));
        setExpr(String(v));
      } catch { setOut("hata"); }
      return;
    }
    setExpr((e) => e + k);
  };
  const clear = () => { setExpr(""); setOut("0"); };

  return (
    <PanelShell title="Hesap Makinesi" subtitle="Cowork içi hafif yardımcı araç." testId="calc-panel">
      <div className="p-6 max-w-xs mx-auto">
        <div className="glass-soft rounded-lg p-4 mb-3">
          <div className="text-xs text-muted font-mono min-h-[16px]" data-testid="calc-expr">{expr || "\u00A0"}</div>
          <div className="text-3xl font-display text-white text-right" data-testid="calc-out">{out}</div>
        </div>
        <div className="grid grid-cols-4 gap-2">
          {BTNS.flat().map((k) => (
            <Btn
              key={k}
              onClick={() => push(k)}
              kind={k === "=" ? "primary" : "subtle"}
              data-testid={`calc-btn-${k}`}
            >{k}</Btn>
          ))}
          <Btn onClick={clear} kind="danger" className="col-span-4" data-testid="calc-clear">Temizle</Btn>
        </div>
      </div>
    </PanelShell>
  );
}
