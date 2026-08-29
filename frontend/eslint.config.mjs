import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
  {
    // components/ui/** is vendored verbatim from shadcn/ui — held to shadcn's
    // own standard, not ours. The newest react-hooks rules (purity,
    // set-state-in-effect) flag idioms in that upstream code we don't hand-edit.
    files: ["components/ui/**"],
    rules: {
      "react-hooks/purity": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
]);

export default eslintConfig;
