import { useMemo } from "react";
import { cn } from "@/lib/utils";

interface GaugeProps {
  value: number; // 0-100
  size?: "small" | "medium" | "large";
  colors?: Record<string, string>;
  showValue?: boolean;
  className?: string;
}

export function Gauge({
  value,
  size = "medium",
  colors,
  showValue = true,
  className,
}: GaugeProps) {
  const clampedValue = Math.max(0, Math.min(100, value));

  const sizeClasses = {
    small: "h-12 w-12",
    medium: "h-20 w-20",
    large: "h-32 w-32",
  };

  const textSizeClasses = {
    small: "text-xs",
    medium: "text-sm",
    large: "text-2xl",
  };

  // Determine color based on value and color stops
  const strokeColor = useMemo(() => {
    if (!colors) {
      // Default color scheme
      if (clampedValue >= 80) return "hsl(var(--destructive))";
      if (clampedValue >= 60) return "hsl(var(--warning))";
      return "hsl(var(--accent))";
    }

    const stops = Object.entries(colors)
      .map(([threshold, color]) => ({ threshold: parseInt(threshold), color }))
      .sort((a, b) => b.threshold - a.threshold);

    for (const stop of stops) {
      if (clampedValue >= stop.threshold) {
        return stop.color;
      }
    }

    return colors["0"] || "hsl(var(--muted))";
  }, [clampedValue, colors]);

  // Convert percentage to angle (full circle = 360°, but gauge is typically 270°)
  const startAngle = -135; // Start at 7 o'clock position
  const endAngle = 135; // End at 5 o'clock position
  const totalAngle = endAngle - startAngle;

  const radius = 45;
  const strokeWidth = 8;
  const circumference = 2 * Math.PI * radius;
  const arcLength = (totalAngle / 360) * circumference;
  const dashOffset = arcLength - (clampedValue / 100) * arcLength;

  return (
    <div className={cn("relative inline-flex items-center justify-center", sizeClasses[size], className)}>
      <svg
        viewBox="0 0 100 100"
        className="w-full h-full -rotate-90"
      >
        {/* Background arc */}
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke="hsl(var(--muted))"
          strokeWidth={strokeWidth}
          strokeDasharray={`${arcLength} ${circumference}`}
          strokeDashoffset={-circumference / 4}
          strokeLinecap="round"
          opacity={0.2}
        />
        {/* Progress arc */}
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeDasharray={`${arcLength} ${circumference}`}
          strokeDashoffset={-circumference / 4 + dashOffset}
          strokeLinecap="round"
          className="transition-all duration-500 ease-out"
        />
      </svg>
      {showValue && (
        <div className={cn(
          "absolute inset-0 flex items-center justify-center font-mono font-semibold",
          textSizeClasses[size]
        )}>
          {Math.round(clampedValue)}%
        </div>
      )}
    </div>
  );
}
