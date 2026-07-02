/**
 * Helper utilities for testing dark mode class presence
 * Use these utilities to verify Tailwind dark: classes in your components
 */

/**
 * Helper to check if an element has dark mode variant classes
 * @param element - The HTML element to check
 * @param classPrefix - The light mode class (e.g., 'bg-white') or dark class to find (e.g., 'dark:bg-gray-900')
 * @returns boolean - true if dark: variant is present
 */
export function hasDarkModeClass(element: HTMLElement, searchClass: string): boolean {
  const className = element.className;
  // If the search class already has dark: prefix, look for it directly
  if (searchClass.startsWith("dark:")) {
    return className.includes(searchClass);
  }
  // Otherwise, check if there's any dark: variant for this class
  // For color classes, check if dark: variants exist
  return className.split(" ").some((cls) => cls.startsWith("dark:"));
}

/**
 * Helper to extract all dark: classes from an element
 * @param element - The HTML element to check
 * @returns string[] - Array of dark mode classes
 */
export function getDarkModeClasses(element: HTMLElement): string[] {
  return element.className.split(" ").filter((cls) => cls.startsWith("dark:"));
}

/**
 * Helper to verify theme class structure
 * @param element - The HTML element to verify
 * @param lightClass - Expected light mode class
 * @param darkClass - Expected dark mode class (without 'dark:' prefix)
 * @returns boolean - true if both classes are present
 */
export function hasThemeVariants(element: HTMLElement, lightClass: string, darkClass: string): boolean {
  const lightPresent = element.className.includes(lightClass);
  const darkPresent = element.className.includes(`dark:${darkClass}`);
  return lightPresent && darkPresent;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Dark Mode Test Helpers", () => {
  let testElement: HTMLElement;

  beforeEach(() => {
    testElement = document.createElement("div");
    document.body.appendChild(testElement);
  });

  afterEach(() => {
    document.body.removeChild(testElement);
  });

  it("hasDarkModeClass detects dark: prefix classes", () => {
    testElement.className = "bg-white dark:bg-gray-900 text-black dark:text-white";

    // Has any dark: classes
    expect(hasDarkModeClass(testElement, "dark:bg-gray-900")).toBe(true);
    expect(hasDarkModeClass(testElement, "dark:text-white")).toBe(true);
    // Element has dark: variants even for light classes
    expect(hasDarkModeClass(testElement, "bg-white")).toBe(true);
  });

  it("getDarkModeClasses extracts all dark mode classes", () => {
    testElement.className = "bg-white dark:bg-gray-900 text-black dark:text-white p-4";

    const darkClasses = getDarkModeClasses(testElement);

    expect(darkClasses).toEqual(["dark:bg-gray-900", "dark:text-white"]);
  });

  it("hasThemeVariants checks for both light and dark variants", () => {
    testElement.className = "bg-white dark:bg-gray-900 px-3";

    // Light class present and dark variant present
    expect(hasThemeVariants(testElement, "bg-white", "bg-gray-900")).toBe(true);
    // Light class present but wrong dark variant
    expect(hasThemeVariants(testElement, "bg-white", "bg-black")).toBe(false);
    // Missing light class entirely
    testElement.className = "dark:text-white px-3";
    expect(hasThemeVariants(testElement, "text-gray-900", "text-white")).toBe(false);
  });
});
