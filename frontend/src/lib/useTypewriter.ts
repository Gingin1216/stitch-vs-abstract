import { useEffect, useState } from "react";

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function useTypewriter(text: string, speed = 28): string {
  const [visibleText, setVisibleText] = useState(text);

  useEffect(() => {
    if (prefersReducedMotion()) {
      setVisibleText(text);
      return;
    }

    setVisibleText("");
    let index = 0;
    const timer = window.setInterval(() => {
      index += 1;
      setVisibleText(text.slice(0, index));
      if (index >= text.length) {
        window.clearInterval(timer);
      }
    }, speed);

    return () => window.clearInterval(timer);
  }, [speed, text]);

  return visibleText;
}
