"use client";

import { motion } from "framer-motion";
import type { UserMessage as UserMessageType } from "@/lib/types";

export function UserMessage({ message }: { message: UserMessageType }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex justify-end"
    >
      <div className="max-w-[70%] rounded-2xl rounded-br-md bg-primary px-4 py-3 text-sm text-primary-foreground shadow-sm">
        {message.content}
      </div>
    </motion.div>
  );
}
