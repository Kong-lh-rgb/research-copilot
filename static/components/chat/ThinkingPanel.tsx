"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

type ThinkingPanelProps = {
  steps: string[];
  collapsed: boolean;
  onToggle: (open: boolean) => void;
};

export function ThinkingPanel({ steps, collapsed, onToggle }: ThinkingPanelProps) {
  const hasSteps = steps.length > 0;

  // 没有思考内容时不渲染
  if (!hasSteps) return null;

  return (
    <Accordion type="single" collapsible value={collapsed ? "" : "thinking"} onValueChange={(value) => onToggle(value === "thinking")}
    >
      <AccordionItem value="thinking" className="border-none">
        <AccordionTrigger className="py-2 text-sm text-muted-foreground hover:no-underline">
          思考过程
        </AccordionTrigger>
        <AccordionContent>
          <AnimatePresence initial={false}>
            {hasSteps && (
              <motion.ul
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                className="space-y-2 rounded-xl border border-dashed border-border/60 bg-muted/30 px-4 py-3 text-xs text-muted-foreground"
              >
                {steps.map((step, index) => (
                  <li key={`${step}-${index}`} className="flex items-start gap-2">
                    <span className="mt-1 h-2 w-2 rounded-full bg-muted-foreground/40" />
                    <span>{step}</span>
                  </li>
                ))}
              </motion.ul>
            )}
          </AnimatePresence>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
