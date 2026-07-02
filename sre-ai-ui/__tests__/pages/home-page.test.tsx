jest.mock("@/components/ChatInterface", () => ({
  ChatInterface: () => {
    const React = require("react");
    return React.createElement("div", { "data-testid": "chat-interface" });
  },
}));

import { redirect } from "next/navigation";
import Home from "@/app/page";

afterEach(() => jest.clearAllMocks());

describe("Home page", () => {
  it("redirects to /api/auth/callback when code and state params are present", async () => {
    await Home({ searchParams: Promise.resolve({ code: "mycode", state: "mystate" }) });
    expect(redirect).toHaveBeenCalledTimes(1);
    const url = (redirect as jest.Mock).mock.calls[0][0] as string;
    expect(url).toContain("/api/auth/callback");
    expect(url).toContain("code=mycode");
    expect(url).toContain("state=mystate");
  });

  it("redirects to /api/auth/callback when error param is present", async () => {
    await Home({ searchParams: Promise.resolve({ error: "access_denied" }) });
    expect(redirect).toHaveBeenCalledTimes(1);
    const url = (redirect as jest.Mock).mock.calls[0][0] as string;
    expect(url).toContain("/api/auth/callback");
    expect(url).toContain("error=");
  });

  it("includes error_description in redirect when both error and error_description are present", async () => {
    await Home({
      searchParams: Promise.resolve({
        error: "access_denied",
        error_description: "User denied access",
      }),
    });
    expect(redirect).toHaveBeenCalledTimes(1);
    const url = (redirect as jest.Mock).mock.calls[0][0] as string;
    expect(url).toContain("error_description");
  });

  it("renders ChatInterface when no OAuth params present", async () => {
    const result = await Home({ searchParams: Promise.resolve({}) });
    expect(redirect).not.toHaveBeenCalled();
    expect(result).not.toBeNull();
    expect(result).not.toBeUndefined();
  });

  it("does not redirect when only code is present (missing state)", async () => {
    await Home({ searchParams: Promise.resolve({ code: "onlycode" }) });
    expect(redirect).not.toHaveBeenCalled();
  });
});
