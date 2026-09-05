import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { OrbProvider } from "@/state/orb";
import TopBar from "@/components/TopBar";
import CommandPalette from "@/components/CommandPalette";
import MiniOrb from "@/components/MiniOrb";
import Home from "@/pages/Home";
import Chat from "@/pages/Chat";
import Cowork from "@/pages/Cowork";
import { Toaster } from "sonner";

const APPLE = [0.32, 0.72, 0, 1];

const variants = {
  initial: { opacity: 0, y: 56, scale: 0.96, filter: "blur(14px)" },
  enter:   { opacity: 1, y: 0,  scale: 1,    filter: "blur(0px)",  transition: { duration: 0.62, ease: APPLE } },
  exit:    { opacity: 0, y: -24, scale: 1.02, filter: "blur(10px)", transition: { duration: 0.38, ease: APPLE } },
};

function AnimatedRoutes() {
  const location = useLocation();
  return (
    <AnimatePresence initial={false}>
      <motion.div
        key={location.pathname}
        className="absolute inset-0"
        variants={variants}
        initial="initial"
        animate="enter"
        exit="exit"
        data-testid="page-transition"
      >
        <Routes location={location}>
          <Route path="/" element={<Home />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/cowork" element={<Cowork />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </motion.div>
    </AnimatePresence>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <OrbProvider>
        <div className="jarvis-shell fixed inset-0" />
        <TopBar />
        <CommandPalette />
        <div className="relative h-dvh w-screen overflow-hidden">
          <AnimatedRoutes />
        </div>
        <MiniOrb />
        <Toaster theme="dark" position="bottom-left" />
      </OrbProvider>
    </BrowserRouter>
  );
}
